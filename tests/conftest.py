import asyncio

import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def _never_spawn_a_real_brain(monkeypatch):
    """server.lifespan builds the brain but must not start `claude` under test."""
    monkeypatch.setenv("JARVIS_BRAIN_AUTOSTART", "0")


@pytest.fixture(autouse=True)
def _never_post_a_real_notification(monkeypatch, request):
    """No test may spam the developer's desktop with notifications.

    Patched on the `notifier` module object itself rather than on `server`, so
    the `importlib.reload(server_module)` that several test fixtures do cannot
    hand the real implementation back. test_windows_port.py is exempt: it tests
    notify() itself and mocks the subprocess boundary directly.
    """
    if request.module.__name__.endswith("test_windows_port"):
        return
    import notifier

    async def _blocked(*args, **kwargs):
        raise AssertionError("a test tried to post a real desktop notification; "
                             "mock notifier.notify")

    monkeypatch.setattr(notifier, "notify", _blocked)


@pytest.fixture(autouse=True)
def _never_touch_the_real_projects_folder(monkeypatch, tmp_path):
    """No test may create a directory in the user's real ~/Projects.

    `create_project` writes into JARVIS_PROJECTS_DIR (default ~/Projects) and
    will create that root if it is missing, so the default is redirected into
    a tmp_path for every test — the same reasoning as JARVIS_DATA_DIR. A test
    that wants its own root still sets the variable itself; this only fills in
    a safe default.
    """
    monkeypatch.setenv("JARVIS_PROJECTS_DIR", str(tmp_path / "projects-root"))


@pytest.fixture(autouse=True)
def _never_write_to_the_live_dotenv(monkeypatch, tmp_path):
    """No test may write into the developer's live `.env`.

    Found the hard way: the settings endpoints write straight into the
    repository's own .env, so a test that posted a preference silently
    rewrote the developer's real configuration — and a test written to
    prove `.env` line injection injected the line for real. Same reasoning
    as JARVIS_DATA_DIR; a test that wants its own file still sets the
    variable itself.
    """
    monkeypatch.setenv("JARVIS_ENV_FILE", str(tmp_path / "dotenv" / ".env"))


@pytest.fixture(autouse=True)
def _never_write_to_the_live_data_dir(monkeypatch, tmp_path):
    """No test may write into the user's real `data/`.

    Most tests already set JARVIS_DATA_DIR (and still do — this only fills in
    a safe default), but a test that merely drives the brain writes there too
    now that a rate-limit event is persisted: without this, running the suite
    overwrote the live usage reading with a fixture's fake one.
    """
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data-dir"))


@pytest_asyncio.fixture(autouse=True)
async def _no_run_left_mid_flight():
    """No test may end with a run's driver still starting its child.

    The CI hang, twice, on Python 3.12 and never on 3.13:
    a test spawned a run, asserted on the row, and returned in the same
    millisecond — while `RunExecutor._drive` was still inside
    `asyncio.create_subprocess_exec`, before the child existed. The loop's
    teardown then cancelled that task mid-spawn, and 3.12's subprocess
    transport never completes a cancellation delivered there: the suite sat
    in `_cancel_all_tasks` until GitHub killed the job 25 minutes later.
    3.13 completes it, which is why no local run ever showed it.

    So every driver alive at the end of a test is waited for here, inside
    the test's own loop, before the runner closes it. A test's fake `claude`
    exits in milliseconds, so the wait is normally nothing; a driver that
    is queued or reading forever is cancelled only after it has had time to
    get past the spawn, which is the one place cancellation must not land.
    """
    yield
    me = asyncio.current_task()

    def _alive(qualname: str) -> list:
        return [t for t in asyncio.all_tasks()
                if t is not me and not t.done()
                and getattr(t.get_coro(), "__qualname__", "") == qualname]

    # First, the exact place: asyncio's own pipe-connection task, which
    # exists only between fork and "the child is up". Whoever spawned it
    # (a run driver, the brain, a fake process) is parked on it. Let it
    # finish — milliseconds — and yield once so the spawner moves on.
    connecting = _alive("BaseSubprocessTransport._connect_pipes")
    if connecting:
        await asyncio.wait(connecting, timeout=5)
        await asyncio.sleep(0)
    # Then a run driver still going: give it time to end on its own (a
    # test's fake claude exits at once) before it is cancelled somewhere
    # safe to cancel.
    drivers = _alive("RunExecutor._drive")
    if not drivers:
        return
    _done, pending = await asyncio.wait(drivers, timeout=10)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=5)


# --- Windows -----------------------------------------------------------------
# What is skipped here is skipped because the test exercises something that
# does not exist on Windows (unix-domain sockets, POSIX file modes, shell-script
# fakes) or builds a file name Windows forbids. Every skip names its reason; nothing is skipped
# because it failed for a reason nobody has looked at.
import sys

# `os.kill(pid, 0)` is the POSIX idiom for "is it alive?" and the tests use it
# as one. On Windows CPython sends every signal but CTRL_C_EVENT/CTRL_BREAK_EVENT
# as TerminateProcess, so the probe KILLS the process it asks about (and was
# seen taking pytest itself down with a KeyboardInterrupt). Here it is the
# liveness check the idiom means.
if sys.platform == "win32":
    import os as _os
    import signal as _signal
    import session_watch as _session_watch

    _real_kill = _os.kill

    def _safe_kill(pid, sig):
        if sig == 0:
            if not _session_watch.pid_alive(pid):
                raise ProcessLookupError(pid)
            return None
        return _real_kill(pid, sig)

    _os.kill = _safe_kill

_WINDOWS_SKIPS_BY_MODULE = {
    "test_session_steer": "steering needs unix-domain sockets (AF_UNIX)",
}
_WINDOWS_SKIPS_BY_TEST = {
    "test_the_repository_name_is_an_argument_and_never_a_shell_string": "fake `gh` is a shell script",
    "test_a_search_query_can_never_be_read_as_a_flag": "fake `gh` is a shell script",
    "test_the_token_file_is_not_world_readable": "POSIX file modes",
    "test_ensure_tool_token_fixes_permissions_of_a_pre_existing_file": "POSIX file modes",
    "test_a_symlink_in_the_token_path_is_refused_not_followed": "POSIX file modes / O_NOFOLLOW",
    "test_the_generated_mcp_config_is_not_world_readable": "POSIX file modes",
    "test_a_pre_existing_mcp_config_has_its_mode_forced_back": "POSIX file modes",
    "test_a_terminal_opens_in_the_project": "asserts POSIX cd quoting (cmd quoting: test_windows_port)",
    "test_open_in_terminal_calls_actions": "asserts POSIX cd quoting (cmd quoting: test_windows_port)",
    "test_open_in_browser_calls_actions_with_a_file_uri": "POSIX-style fake path has no file URI on Windows",
    "test_a_file_the_repository_named_is_not_spoken_raw": "builds a file name with a newline",
    "test_a_hostile_filename_cannot_escape_read_files_block": "builds a file name with quotes",
    "test_a_hostile_filename_cannot_stand_outside_the_block_either": "builds a file name with a newline",
    "test_a_hostile_project_name_cannot_write_a_tag": "builds a directory name with quotes",
    "test_a_replaced_file_at_the_same_path_and_size_is_read_from_the_start":
        "compares byte sizes of a file written in text mode (CRLF)",
    "test_a_transcript_that_could_not_be_read_is_not_measured": "denies reads with chmod 000",
    "test_one_unreadable_file_does_not_unmeasure_the_readable_ones": "denies reads with chmod 000",
}


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    for item in items:
        reason = (_WINDOWS_SKIPS_BY_MODULE.get(item.module.__name__.split(".")[-1])
                  or _WINDOWS_SKIPS_BY_TEST.get(item.name)
                  or ("SIGSTOP does not exist" if item.name.endswith("[sigstop]") else None))
        if reason:
            item.add_marker(pytest.mark.skip(reason=f"Windows: {reason}"))
