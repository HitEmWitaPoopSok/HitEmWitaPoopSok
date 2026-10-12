"""The Windows paths, exercised from any platform.

`sys.platform` is flipped to "win32" and every process boundary is faked, so
these run on the Linux box as well as on a Windows runner. What they pin is
the *shape* of each Windows branch: which program is spawned, that untrusted
text travels in the environment and never in script source, and that the
modules that cannot work on Windows refuse rather than guess.
"""
import asyncio
import base64
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import actions
import data_paths
import dialog
import notifier
import preflight
import screen
import winutil

REPO = Path(__file__).parent.parent


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    # shutil.which consults the Win32 API once sys.platform says win32.
    monkeypatch.setattr(winutil.shutil, "which", lambda *a, **k: None)


# ── actions ────────────────────────────────────────────────────────────────

def test_cd_command_quotes_for_cmd(windows):
    assert actions.cd_command(r"C:\Users\me\My Project") == r'cd /d "C:\Users\me\My Project"'


def test_cd_command_cannot_be_quoted_out_of(windows):
    out = actions.cd_command('C:\\x" & calc & "')
    assert out.count('"') == 2           # only the pair we added
    assert out.startswith('cd /d "') and out.endswith('"')


def test_cd_command_defuses_percent_expansion(windows):
    assert "%%PATH%%" in actions.cd_command(r"C:\%PATH%")


def test_cd_command_is_shlex_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert actions.cd_command("/a b/c") == "cd '/a b/c'"


@pytest.mark.asyncio
async def test_open_terminal_launches_a_console(windows):
    calls = []
    with patch("actions.subprocess.Popen", side_effect=lambda *a, **k: calls.append((a, k))):
        result = await actions.open_terminal('cd /d "C:\\p" && npm start')
    assert result["success"] is True
    (line,), kwargs = calls[0]
    assert "/S /K" in line and line.endswith('npm start"')
    assert kwargs["creationflags"] == actions._CREATE_NEW_CONSOLE


@pytest.mark.asyncio
async def test_open_browser_refuses_a_flag_shaped_url(windows):
    with patch("actions.subprocess.Popen") as popen:
        result = await actions.open_browser("--remote-debugging-port=1", "chrome")
    assert result["success"] is False
    popen.assert_not_called()


@pytest.mark.asyncio
async def test_open_browser_runs_the_exe_with_the_url_as_one_argument(windows):
    with patch("actions._windows_browser_exe", return_value=r"C:\chrome.exe"), \
         patch("actions.subprocess.Popen") as popen:
        result = await actions.open_browser("https://example.com/a b", "chrome")
    assert result["success"] is True
    assert popen.call_args.args[0] == [r"C:\chrome.exe", "https://example.com/a b"]


@pytest.mark.asyncio
async def test_chrome_tab_info_is_empty_on_windows(windows):
    assert await actions.get_chrome_tab_info() == {}


# ── notifier ───────────────────────────────────────────────────────────────

class _Proc:
    returncode = 0

    async def communicate(self, input=None):
        return b"", b""


@pytest.mark.asyncio
async def test_windows_notification_keeps_text_out_of_the_script(windows):
    seen = {}

    async def fake(*args, **kwargs):
        seen["args"], seen["env"] = args, kwargs["env"]
        return _Proc()

    evil = 'x"; Remove-Item -Recurse C:\\ ; "'
    # _notify_windows, not notify(): conftest blocks notify() for every
    # module but test_notifier, and the routing is a one-line `if`.
    with patch("notifier.asyncio.create_subprocess_exec", side_effect=fake):
        assert await notifier._notify_windows(evil, "body", "sub") is True

    script = base64.b64decode(seen["args"][-1]).decode("utf-16-le")
    assert "Remove-Item" not in script and evil not in script
    assert seen["env"]["JARVIS_NOTIFY_TITLE"] == evil
    assert seen["env"]["JARVIS_NOTIFY_MESSAGE"] == "body"
    assert "-EncodedCommand" in seen["args"]


# ── screen ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_windows_window_list_is_parsed(windows):
    out = "Code|||main.py - jarvis|||True\nchrome|||JARVIS|||False\nbad line\n"

    async def fake_run(*args, timeout, env=None):
        return 0, out, ""

    with patch("screen._run", side_effect=fake_run):
        wins = await screen.list_windows()
    assert [(w.app, w.title, w.frontmost) for w in wins] == [
        ("Code", "main.py - jarvis", True), ("chrome", "JARVIS", False)]


@pytest.mark.asyncio
async def test_windows_window_list_failure_is_spoken(windows):
    async def fake_run(*args, timeout, env=None):
        return 1, "", "boom"

    with patch("screen._run", side_effect=fake_run):
        with pytest.raises(screen.ScreenError):
            await screen.list_windows()


@pytest.mark.asyncio
async def test_windows_capture_reads_the_png_the_script_wrote(windows):
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
           + (640).to_bytes(4, "big") + (360).to_bytes(4, "big") + b"\x08\x06\x00\x00\x00")

    async def fake_run(*args, timeout, env=None):
        Path(env["JARVIS_SHOT_PATH"]).write_bytes(png)
        assert env["JARVIS_SHOT_DISPLAY"] == "2"
        assert env["JARVIS_SHOT_MAX"] == str(screen.SHOT_MAX_EDGE)
        return 0, "", ""

    with patch("screen._run", side_effect=fake_run):
        shot = await screen.capture_screen(display=2)
    assert (shot.width, shot.height) == (640, 360)


@pytest.mark.asyncio
async def test_windows_capture_failure_is_spoken(windows):
    async def fake_run(*args, timeout, env=None):
        return 1, "", "no display"

    with patch("screen._run", side_effect=fake_run):
        with pytest.raises(screen.ScreenError):
            await screen.capture_screen()


# ── dialog / preflight ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dialog_presses_nothing_on_windows(windows):
    with patch("dialog.find_terminal_tab") as find:
        assert await dialog.answer(1234, "return") == dialog.NO_TTY
    find.assert_not_called()


def test_tty_lookup_is_none_on_windows(windows):
    assert dialog.tty_for_pid(1234) is None


@pytest.mark.asyncio
async def test_macos_only_preflight_checks_pass_on_windows(windows):
    assert (await preflight._check_accessibility()).status == preflight.STATUS_OK
    assert preflight._check_screen_recording_sync().status == preflight.STATUS_OK
    assert preflight._check_cross_session_inbound_sync().status == preflight.STATUS_OK


@pytest.mark.asyncio
async def test_oauth_expiry_is_read_from_the_credentials_file(windows, tmp_path):
    (tmp_path / ".credentials.json").write_text(
        '{"claudeAiOauth": {"refreshTokenExpiresAt": 2000000, "accessToken": "secret"}}')
    assert await preflight._read_oauth_refresh_expiry(tmp_path, 1.0) == 2000.0


@pytest.mark.asyncio
async def test_oauth_expiry_unknown_without_the_file(windows, tmp_path):
    assert await preflight._read_oauth_refresh_expiry(tmp_path, 1.0) is None


# ── data_paths ─────────────────────────────────────────────────────────────

def test_tool_token_is_created_and_then_reused_on_windows(windows, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    first = data_paths.ensure_tool_token()
    assert first and data_paths.ensure_tool_token() == first


# ── steering ───────────────────────────────────────────────────────────────

def test_steering_is_not_live_without_unix_sockets(monkeypatch, tmp_path):
    import session_steer
    sock = tmp_path / "x.sock"
    sock.write_text("")
    monkeypatch.delattr(session_steer.socket, "AF_UNIX", raising=False)
    assert session_steer.post_to_session(str(sock), "hello") == session_steer.NOT_LIVE


# ── winutil / launcher ─────────────────────────────────────────────────────

def test_powershell_argv_encodes_the_script():
    argv = winutil.powershell_argv("Write-Output 'é'")
    assert argv[-2] == "-EncodedCommand"
    assert base64.b64decode(argv[-1]).decode("utf-16-le") == "Write-Output 'é'"


def _launcher():
    spec = importlib.util.spec_from_file_location("jarvis_launcher", REPO / "windows" / "launcher.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_launcher_server_env_points_state_at_appdata(tmp_path):
    launcher = _launcher()
    env = launcher.server_env(tmp_path)
    assert env["JARVIS_DATA_DIR"] == str(tmp_path / "data")
    assert env["JARVIS_ENV_FILE"] == str(tmp_path / ".env")
    assert env["JARVIS_PID_FILE"] == str(tmp_path / "jarvis.pid")


def test_launcher_refuses_a_broken_install(tmp_path):
    launcher = _launcher()
    with pytest.raises(FileNotFoundError):
        launcher.start_server(tmp_path, tmp_path / "data")


def test_launcher_spawns_hidden_utf8_server(tmp_path):
    launcher = _launcher()
    (tmp_path / "python").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "python" / "python.exe").write_text("")
    (tmp_path / "app" / "server.py").write_text("")
    with patch.object(launcher.subprocess, "Popen") as popen:
        launcher.start_server(tmp_path, tmp_path / "data")
    argv = popen.call_args.args[0]
    assert argv[1:3] == ["-X", "utf8"] and argv[3].endswith("server.py")
    assert popen.call_args.kwargs["creationflags"] & launcher.CREATE_NO_WINDOW
