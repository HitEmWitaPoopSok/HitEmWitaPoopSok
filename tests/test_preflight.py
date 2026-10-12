"""Tests for preflight.py -- first-run environment checks.

NO TEST IN THIS FILE MAY INVOKE THE REAL `claude` BINARY, THE REAL
PowerShell, OR READ THE DEVELOPER'S REAL ~/.claude/settings.json.

Every subprocess call goes through the single seam `preflight._run_subprocess`
so tests monkeypatch that one
function rather than `asyncio.create_subprocess_exec` per call site. The
settings-file check goes through `preflight._settings_path`, which tests
point at a tmp_path fixture instead of the real home directory.
"""

import asyncio
import json
import time

import pytest

import preflight
from preflight import Check, STATUS_FAIL, STATUS_OK, STATUS_WARN


def _fake_run_subprocess(responses):
    """Build a fake `_run_subprocess` keyed by (args tuple) -> (rc, stdout, stderr).

    Matching is by the first two positional args (e.g. ("claude", "--version")
    ) so callers don't need to know exact remaining
    arguments. Accepts (and ignores)
    the `env` kwarg that `claude_login` now passes.
    """
    async def fake(*args, timeout, env=None):
        key = tuple(args[:2])
        if key in responses:
            return responses[key]
        raise AssertionError(f"unexpected subprocess call: {args}")
    return fake


# --- claude_cli: PATH + version -------------------------------------------

@pytest.mark.asyncio
async def test_claude_missing_from_path(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_FAIL
    assert "PATH" in check.message
    assert check.remedy


@pytest.mark.asyncio
async def test_claude_present_but_too_old(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "--version"): (0, "2.1.9 (Claude Code)\n", "")}),
    )
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_FAIL
    assert "2.1.9" in check.message
    assert check.remedy


@pytest.mark.asyncio
async def test_claude_present_and_new_enough(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "--version"): (0, "2.1.258 (Claude Code)\n", "")}),
    )
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_OK
    assert check.remedy is None


@pytest.mark.asyncio
async def test_claude_exactly_at_minimum_version_is_ok(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "--version"): (0, "2.1.224\n", "")}),
    )
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_OK


def test_version_comparison_is_numeric_not_lexicographic():
    """The whole point of parsing into a tuple of ints: '2.1.9' < '2.1.224'
    numerically even though it is greater lexicographically as a string."""
    assert preflight._parse_version("2.1.9") < preflight.MIN_CLAUDE_VERSION
    assert preflight._parse_version("2.1.224") == preflight.MIN_CLAUDE_VERSION
    assert preflight._parse_version("2.1.258") > preflight.MIN_CLAUDE_VERSION
    assert "2.1.9" > "2.1.224"  # the naive (wrong) string comparison, for contrast


@pytest.mark.asyncio
async def test_claude_version_unparseable_output_is_warn(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "--version"): (0, "garbage\n", "")}),
    )
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_WARN


# --- claude_login -----------------------------------------------------------

def _fake_child_env(monkeypatch, config_dir):
    """Point claude_login's `claude_env.child_env()` call at a fixed,
    test-controlled environment instead of this process's real one, so
    results (and the config dir named in messages) are deterministic."""
    monkeypatch.setattr(
        preflight.claude_env, "child_env",
        lambda: {"CLAUDE_CONFIG_DIR": str(config_dir)},
    )


@pytest.mark.asyncio
async def test_claude_not_logged_in(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    _fake_child_env(monkeypatch, tmp_path / ".claude")
    body = json.dumps({"loggedIn": False})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (0, body, "")}),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_FAIL
    assert "not logged in" in check.message
    assert check.remedy


@pytest.mark.asyncio
async def test_claude_logged_in(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    _fake_child_env(monkeypatch, tmp_path / ".claude")
    body = json.dumps({"loggedIn": True, "email": "you@example.com"})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (0, body, "")}),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_OK
    assert check.remedy is None
    assert "you@example.com" in check.message


@pytest.mark.asyncio
async def test_claude_login_check_without_claude_on_path(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    check = await preflight._check_claude_login()
    assert check.status == STATUS_WARN
    assert check.remedy


@pytest.mark.asyncio
async def test_claude_login_nonzero_exit_is_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    _fake_child_env(monkeypatch, tmp_path / ".claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (1, "", "not logged in at all")}),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_FAIL


@pytest.mark.asyncio
async def test_claude_login_malformed_json_is_warn(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    _fake_child_env(monkeypatch, tmp_path / ".claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (0, "not json{{{", "")}),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_WARN


@pytest.mark.asyncio
async def test_claude_login_names_the_config_dir(monkeypatch, tmp_path):
    """A mismatched CLAUDE_CONFIG_DIR must be visible at a glance in the result."""
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    config_dir = tmp_path / "some-other-config-dir"
    _fake_child_env(monkeypatch, config_dir)
    body = json.dumps({"loggedIn": True, "email": "you@example.com"})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (0, body, "")}),
    )
    check = await preflight._check_claude_login()
    assert str(config_dir) in check.message


# --- FISH_API_KEY -------------------------------------------------------------

def test_fish_api_key_present(monkeypatch):
    monkeypatch.setenv("FISH_API_KEY", "sk-fish-abc123")
    check = preflight._check_fish_api_key_sync()
    assert check.status == STATUS_OK


def test_fish_api_key_absent(monkeypatch):
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    check = preflight._check_fish_api_key_sync()
    assert check.status == STATUS_FAIL
    assert check.remedy


# --- leftover ANTHROPIC_* ------------------------------------------------------

def test_leftover_anthropic_key_warns(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc123")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    check = preflight._check_anthropic_key_leftover_sync()
    assert check.status == STATUS_WARN
    assert "ANTHROPIC_API_KEY" in check.message
    assert check.remedy


def test_no_anthropic_key_is_ok(monkeypatch):
    for key in list(preflight.os.environ):
        if key.startswith("ANTHROPIC_"):
            monkeypatch.delenv(key, raising=False)
    check = preflight._check_anthropic_key_leftover_sync()
    assert check.status == STATUS_OK
    assert check.remedy is None


# --- crossSessionInbound --------------------------------------------------------

# --- run_checks(): timeouts, internal exceptions, concurrency -----------------

@pytest.mark.asyncio
async def test_a_hung_check_times_out_as_warn(monkeypatch):
    async def hang(*, timeout):
        await asyncio.sleep(999)
        return Check(name="claude_cli", status=STATUS_OK, message="unreachable")

    monkeypatch.setattr(preflight, "_ASYNC_CHECKS", (hang,))
    monkeypatch.setattr(preflight, "_SYNC_CHECKS", ())

    results = await preflight.run_checks(timeout=0.05)
    assert len(results) == 1
    assert results[0].status == STATUS_WARN
    assert "timed out" in results[0].message


@pytest.mark.asyncio
async def test_a_raising_check_becomes_warn_not_an_exception(monkeypatch):
    def explode():
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(preflight, "_ASYNC_CHECKS", ())
    monkeypatch.setattr(preflight, "_SYNC_CHECKS", (explode,))

    results = await preflight.run_checks(timeout=1.0)
    assert len(results) == 1
    assert results[0].status == STATUS_WARN
    assert "disk on fire" in results[0].message


@pytest.mark.asyncio
async def test_run_checks_never_raises_even_with_a_broken_check(monkeypatch):
    def explode():
        raise ValueError("boom")

    monkeypatch.setattr(preflight, "_SYNC_CHECKS", (explode,))
    # Should not raise.
    results = await preflight.run_checks(timeout=1.0)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_run_checks_runs_all_registered_checks(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)  # claude missing -> fast fail
    monkeypatch.delenv("FISH_API_KEY", raising=False)

    results = await preflight.run_checks(timeout=1.0)
    names = {c.name for c in results}
    assert names == {"claude_cli", "claude_login", "fish_api_key",
                     "anthropic_key_leftover"}


def _write_credentials(config_dir, expires_at_ms):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / ".credentials.json").write_text(json.dumps(
        {"claudeAiOauth": {"refreshTokenExpiresAt": expires_at_ms, "accessToken": "secret"}}))


_OAUTH_STATUS = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "you@example.com"})


@pytest.mark.asyncio
async def test_claude_login_expired_oauth_session_is_fail_not_ok(monkeypatch, tmp_path):
    """The real incident: `claude auth status` reports loggedIn: true, but the
    stored OAuth refresh token has already expired -- a real turn would fail
    with 'OAuth session expired and could not be refreshed'."""
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    config_dir = tmp_path / ".claude"
    _fake_child_env(monkeypatch, config_dir)
    _write_credentials(config_dir, (time.time() - 3600) * 1000)
    monkeypatch.setattr(preflight, "_run_subprocess", _fake_run_subprocess(
        {("/usr/local/bin/claude", "auth"): (0, _OAUTH_STATUS, "")}))
    check = await preflight._check_claude_login()
    assert check.status == STATUS_FAIL
    assert "expired" in check.message.lower()
    assert check.remedy
    assert "secret" not in check.message


@pytest.mark.asyncio
async def test_claude_login_valid_oauth_session_is_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    config_dir = tmp_path / ".claude"
    _fake_child_env(monkeypatch, config_dir)
    _write_credentials(config_dir, (time.time() + 3600 * 24 * 30) * 1000)
    monkeypatch.setattr(preflight, "_run_subprocess", _fake_run_subprocess(
        {("/usr/local/bin/claude", "auth"): (0, _OAUTH_STATUS, "")}))
    check = await preflight._check_claude_login()
    assert check.status == STATUS_OK
    assert check.remedy is None


@pytest.mark.asyncio
async def test_claude_login_without_a_credentials_file_stays_ok_but_says_so(monkeypatch, tmp_path):
    """When the expiry can't be read, the check must not silently claim more
    certainty than it has."""
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    _fake_child_env(monkeypatch, tmp_path / ".claude")
    monkeypatch.setattr(preflight, "_run_subprocess", _fake_run_subprocess(
        {("/usr/local/bin/claude", "auth"): (0, _OAUTH_STATUS, "")}))
    check = await preflight._check_claude_login()
    assert check.status == STATUS_OK
    assert "could not independently verify" in check.message.lower()


@pytest.mark.asyncio
async def test_claude_login_credentials_garbage_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    (config_dir / ".credentials.json").write_text("not json at all {{{")
    _fake_child_env(monkeypatch, config_dir)
    monkeypatch.setattr(preflight, "_run_subprocess", _fake_run_subprocess(
        {("/usr/local/bin/claude", "auth"): (0, _OAUTH_STATUS, "")}))
    check = await preflight._check_claude_login()  # must not raise
    assert check.status == STATUS_OK
    assert "could not independently verify" in check.message.lower()


# --- spoken_summary -------------------------------------------------------------

def test_spoken_summary_empty_when_all_ok():
    checks = [
        Check(name="claude_cli", status=STATUS_OK, message="ok"),
        Check(name="fish_api_key", status=STATUS_OK, message="ok"),
    ]
    assert preflight.spoken_summary(checks) == ""


def test_spoken_summary_never_says_all_checks_passed():
    checks = [Check(name="claude_cli", status=STATUS_OK, message="ok")]
    summary = preflight.spoken_summary(checks)
    assert summary == ""
    assert "all checks passed" not in summary.lower()


def test_spoken_summary_names_a_single_failure():
    checks = [
        Check(name="claude_cli", status=STATUS_OK, message="ok"),
        Check(name="claude_login", status=STATUS_FAIL, message="Claude Code is not logged in."),
    ]
    summary = preflight.spoken_summary(checks)
    assert "One thing needs attention" in summary
    assert "isn't logged in" in summary
    assert "claude_cli" not in summary  # only the failing check is named


def test_spoken_summary_names_two_failures_and_matches_the_example():
    checks = [
        Check(name="claude_login", status=STATUS_FAIL, message="Claude Code is not logged in."),
        Check(name="fish_api_key", status=STATUS_FAIL, message="FISH_API_KEY is not set."),
    ]
    summary = preflight.spoken_summary(checks)
    assert summary == (
        "Two things need attention, sir: Claude Code isn't logged in, "
        "and I have no Fish Audio key."
    )


def test_spoken_summary_names_only_the_failures_among_a_mix():
    checks = [
        Check(name="claude_cli", status=STATUS_OK, message="ok"),
        Check(name="claude_login", status=STATUS_OK, message="ok"),
        Check(name="fish_api_key", status=STATUS_FAIL, message="FISH_API_KEY is not set."),
        Check(name="anthropic_key_leftover", status=STATUS_WARN, message="ANTHROPIC_API_KEY set"),
    ]
    summary = preflight.spoken_summary(checks)
    assert summary.startswith("Two things need attention, sir:")
    assert "no Fish Audio key" in summary
    assert "leftover Anthropic API key" in summary


def test_spoken_summary_warn_counts_as_something_wrong():
    checks = [Check(name="anthropic_key_leftover", status=STATUS_WARN, message="ANTHROPIC_API_KEY set")]
    summary = preflight.spoken_summary(checks)
    assert summary != ""
    assert "One thing needs attention" in summary
