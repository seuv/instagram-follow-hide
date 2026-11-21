"""Tests for the command-line interface and the interactive menu."""

from __future__ import annotations

import io
import time

import pytest

import privacy as igfp

from .conftest import SESSION_ID


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("IG_SESSIONID", "IG_CLIENT_DOC_ID", "IG_APP_ID", "IG_USER_AGENT", "IG_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def _fake_set(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []

    def fake(self, hidden):
        calls.append(hidden)
        return igfp.SettingResult(user_id="12345678", hidden=hidden)

    monkeypatch.setattr(igfp.InstagramClient, "set_lists_hidden", fake)
    return calls


def _keys(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it))


# -- one-shot commands ---------------------------------------------------------------


def test_subcommand_is_required() -> None:
    with pytest.raises(SystemExit) as info:
        igfp.build_parser().parse_args([])
    assert info.value.code == 2


def test_no_args_without_terminal_is_usage_error(capsys) -> None:
    assert igfp.main([]) == igfp.EXIT_USAGE
    assert "needs a terminal" in capsys.readouterr().err


def test_dry_run_does_not_touch_network(monkeypatch, capsys) -> None:
    monkeypatch.setenv("IG_SESSIONID", SESSION_ID)

    def boom(*_a, **_k):
        raise AssertionError("network must not be used in dry-run")

    monkeypatch.setattr(igfp.InstagramClient, "set_lists_hidden", boom)
    assert igfp.main(["hide", "--dry-run", "--no-banner"]) == 0
    out = capsys.readouterr().out
    assert "hide_followers_following_list=true" in out
    assert "12345678" in out
    assert "https://i.instagram.com/graphql/query" in out
    assert SESSION_ID not in out


def test_dry_run_unhide_reports_false(monkeypatch, capsys) -> None:
    monkeypatch.setenv("IG_SESSIONID", SESSION_ID)
    assert igfp.main(["unhide", "--dry-run"]) == 0
    assert "=false" in capsys.readouterr().out


@pytest.mark.parametrize(("command", "hidden"), [("hide", True), ("unhide", False)])
def test_success_messages(monkeypatch, capsys, command: str, hidden: bool) -> None:
    monkeypatch.setenv("IG_SESSIONID", SESSION_ID)
    calls = _fake_set(monkeypatch)
    assert igfp.main([command]) == 0
    assert calls == [hidden]
    assert f"value={str(hidden).lower()}" in capsys.readouterr().out


def test_reads_session_from_stdin(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(SESSION_ID + "\n"))
    assert igfp.main(["hide", "--stdin", "--dry-run"]) == 0
    assert "12345678" in capsys.readouterr().out


def test_hidden_prompt_is_used_when_nothing_else(monkeypatch, capsys) -> None:
    monkeypatch.setattr("getpass.getpass", lambda _p="": SESSION_ID)
    assert igfp.main(["hide", "--dry-run"]) == 0
    assert "12345678" in capsys.readouterr().out


def test_invalid_session_exit_code(monkeypatch, capsys) -> None:
    monkeypatch.setenv("IG_SESSIONID", "sessionid=oops")
    assert igfp.main(["hide"]) == 1
    assert "without 'sessionid='" in capsys.readouterr().err


def test_client_error_exit_code(monkeypatch, capsys) -> None:
    monkeypatch.setenv("IG_SESSIONID", SESSION_ID)

    def fail(self, hidden):
        raise igfp.SettingNotConfirmedError("not confirmed")

    monkeypatch.setattr(igfp.InstagramClient, "set_lists_hidden", fail)
    assert igfp.main(["hide"]) == 1
    captured = capsys.readouterr()
    assert "not confirmed" in captured.err
    assert SESSION_ID not in captured.out + captured.err


def test_bad_config_flag(monkeypatch, capsys) -> None:
    monkeypatch.setenv("IG_SESSIONID", SESSION_ID)
    assert igfp.main(["hide", "--dry-run", "--doc-id", "abc"]) == 1
    assert "doc id" in capsys.readouterr().err


def test_no_banner_when_not_a_terminal(monkeypatch, capsys) -> None:
    monkeypatch.setenv("IG_SESSIONID", SESSION_ID)
    igfp.main(["hide", "--dry-run"])
    assert "unofficial" not in capsys.readouterr().out


# -- console ---------------------------------------------------------------------------


def test_console_plain_when_color_disabled(capsys) -> None:
    c = igfp.Console(color=False)
    c.ok("session", "fine")
    c.err("session", "bad")
    c.banner(clear=True)
    captured = capsys.readouterr()
    assert "\x1b[" not in captured.out + captured.err
    assert "✓ session · fine" in captured.out
    assert "✗ session · bad" in captured.err
    assert "unofficial" in captured.out


def test_console_colors_when_enabled(capsys) -> None:
    igfp.Console(color=True).ok("x", "y")
    assert "\x1b[92m" in capsys.readouterr().out


# -- interactive menu --------------------------------------------------------------------


def _app(monkeypatch, **kwargs) -> igfp.App:
    creds = igfp.Credentials.from_session_id(SESSION_ID)
    return igfp.App(igfp.Console(color=False), igfp.ClientConfig(), creds, **kwargs)


def test_menu_hide_then_unhide_then_exit(monkeypatch, capsys) -> None:
    calls = _fake_set(monkeypatch)
    _keys(monkeypatch, ["1", "", "2", "", "5"])
    assert _app(monkeypatch).run() == 0
    assert calls == [True, False]
    out = capsys.readouterr().out
    assert "lists are now hidden" in out
    assert "lists are now visible" in out
    assert "last action" in out


def test_menu_preview_and_invalid_option(monkeypatch, capsys) -> None:
    calls = _fake_set(monkeypatch)
    _keys(monkeypatch, ["3", "", "9", "q"])
    assert _app(monkeypatch).run() == 0
    assert calls == []
    captured = capsys.readouterr()
    assert "no request was sent" in captured.out
    assert "invalid option" in captured.err


def test_menu_failure_is_reported_and_loop_continues(monkeypatch, capsys) -> None:
    def fail(self, hidden):
        raise igfp.RequestError("HTTP 400: boom. No retry performed.")

    monkeypatch.setattr(igfp.InstagramClient, "set_lists_hidden", fail)
    _keys(monkeypatch, ["1", "", ""])
    assert _app(monkeypatch).run() == 0
    assert "HTTP 400" in capsys.readouterr().err


def test_menu_login_from_prompt_with_retry(monkeypatch, capsys) -> None:
    answers = iter(["bad value", SESSION_ID])
    monkeypatch.setattr("getpass.getpass", lambda _p="": next(answers))
    _keys(monkeypatch, [""])
    app = igfp.App(igfp.Console(color=False), igfp.ClientConfig())
    assert app.run() == 0
    captured = capsys.readouterr()
    assert "user id 12345678" in captured.out
    assert SESSION_ID not in captured.out + captured.err


def test_menu_login_uses_env_and_can_be_cancelled(monkeypatch, capsys) -> None:
    monkeypatch.setenv("IG_SESSIONID", SESSION_ID)
    _keys(monkeypatch, [""])
    assert igfp.App(igfp.Console(color=False), igfp.ClientConfig()).run() == 0

    monkeypatch.delenv("IG_SESSIONID")
    monkeypatch.setattr("getpass.getpass", lambda _p="": "")
    assert igfp.App(igfp.Console(color=False), igfp.ClientConfig()).run() == 1


def test_menu_change_session_keeps_old_when_cancelled(monkeypatch, capsys) -> None:
    monkeypatch.setattr("getpass.getpass", lambda _p="": "")
    _keys(monkeypatch, ["4", "5"])
    app = _app(monkeypatch)
    assert app.run() == 0
    assert app.credentials is not None and app.credentials.user_id == "12345678"
    assert "session unchanged" in capsys.readouterr().out
