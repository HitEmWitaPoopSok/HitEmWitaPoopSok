"""The Windows code paths, exercised from any platform.

Every process boundary is faked, so these run on a Linux dev box as well as on
a Windows runner. What they pin is the *shape* of each path: which program is
spawned, and that untrusted text travels in the environment and never in
script source.
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


@pytest.mark.asyncio
async def test_notify_reports_success_and_failure():
    for code, expected in ((0, True), (1, False)):
        proc = _Proc()
        proc.returncode = code

        async def fake(*args, **kwargs):
            return proc

        with patch("notifier.available", return_value=True), \
             patch("notifier.asyncio.create_subprocess_exec", side_effect=fake):
            assert await notifier.notify("t", "m") is expected


@pytest.mark.asyncio
async def test_notify_is_false_without_powershell():
    with patch("notifier.available", return_value=False):
        assert await notifier.notify("t", "m") is False


@pytest.mark.asyncio
async def test_notify_bounds_what_it_passes_on():
    seen = {}

    async def fake(*args, **kwargs):
        seen.update(kwargs["env"])
        return _Proc()

    with patch("notifier.available", return_value=True), \
         patch("notifier.asyncio.create_subprocess_exec", side_effect=fake):
        await notifier.notify("T" * 500, "M" * 5000, subtitle="S" * 500)
    assert len(seen["JARVIS_NOTIFY_TITLE"]) <= notifier._TITLE_MAX
    assert len(seen["JARVIS_NOTIFY_MESSAGE"]) <= notifier._MESSAGE_MAX
    assert seen["JARVIS_NOTIFY_MESSAGE"].endswith("…")


@pytest.mark.asyncio
async def test_notify_never_raises():
    async def boom(*a, **k):
        raise OSError("no powershell")

    with patch("notifier.available", return_value=True), \
         patch("notifier.asyncio.create_subprocess_exec", side_effect=boom):
        assert await notifier.notify("t", "m") is False


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


# ── claude command / project paths ─────────────────────────────────────────

def test_a_windows_claude_path_survives_being_split(monkeypatch):
    import claude_env
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(claude_env.os.path, "isfile", lambda p: False)
    assert claude_env.command_argv(r"C:\Users\me\AppData\Roaming\npm\claude.cmd") == [
        r"C:\Users\me\AppData\Roaming\npm\claude.cmd"]
    assert claude_env.command_argv(r'"C:\Program Files\x\py.exe" C:\t\fake.py') == [
        r"C:\Program Files\x\py.exe", r"C:\t\fake.py"]


def test_an_existing_path_with_spaces_is_one_argument(tmp_path):
    import claude_env
    exe = tmp_path / "a dir" / "claude"
    exe.parent.mkdir()
    exe.write_text("")
    assert claude_env.command_argv(str(exe)) == [str(exe)]


def test_posix_splitting_is_unchanged():
    import claude_env
    assert claude_env.command_argv("python3 /tmp/x y.py") == ["python3", "/tmp/x", "y.py"]


def test_windows_project_paths_are_speakable():
    import server
    assert server._project_path_speakable(r"C:\Users\me\projects\chitauri")
    assert server._project_path_speakable("D:/work/chitauri")
    assert server._project_path_speakable("/home/me/chitauri")
    assert not server._project_path_speakable("relative/path")
    assert not server._project_path_speakable('C:\\x"><b')


def test_a_written_template_is_byte_identical_to_the_text(tmp_path):
    """On Windows a text-mode write turns "\\n" into "\\r\\n", which made an
    unedited persona hash differently from the template and never update."""
    target = tmp_path / "CLAUDE.md"
    text = "# JARVIS\n\nline two\n"
    assert data_paths._write_atomically(target, text)
    assert target.read_bytes() == text.encode("utf-8")
