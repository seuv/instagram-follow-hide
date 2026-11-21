"""Tests for the HTTP client using a fake opener (no network)."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse

import pytest

from privacy import (
    ClientConfig,
    ConfigurationError,
    InstagramClient,
    RequestError,
    SettingNotConfirmedError,
    redact,
)

from .conftest import ROOT, SESSION_ID, FakeOpener, ok_payload


def _form(opener: FakeOpener) -> dict[str, str]:
    request, _ = opener.calls[0]
    return {k: v[0] for k, v in urllib.parse.parse_qs(request.data.decode()).items()}


@pytest.mark.parametrize("hidden", [True, False])
def test_success_sends_requested_value(credentials, hidden: bool) -> None:
    opener = FakeOpener(ok_payload(hidden))
    result = InstagramClient(credentials, opener=opener).set_lists_hidden(hidden)

    assert result.hidden is hidden
    assert result.user_id == "12345678"
    assert len(opener.calls) == 1  # never retried
    form = _form(opener)
    variables = json.loads(form["variables"])
    assert variables["setting_id"] == "hide_followers_following_list"
    assert variables["value"] is hidden
    assert form["client_doc_id"] == ClientConfig().doc_id


def test_request_headers_and_target(credentials) -> None:
    opener = FakeOpener(ok_payload(True))
    InstagramClient(credentials, opener=opener).set_lists_hidden(True)
    request, timeout = opener.calls[0]
    assert request.full_url == "https://i.instagram.com/graphql/query"
    assert request.get_method() == "POST"
    assert request.get_header("Ig-intended-user-id") == "12345678"
    assert request.get_header("Authorization") == credentials.authorization
    assert timeout == 15.0


def test_response_key_with_arguments_is_accepted(credentials) -> None:
    opener = FakeOpener(ok_payload(True, key=f"{ROOT}(input:{{}})"))
    assert InstagramClient(credentials, opener=opener).set_lists_hidden(True).hidden is True


def test_custom_config_is_used(credentials) -> None:
    cfg = ClientConfig(doc_id="42", app_id="7", user_agent="UA/1", timeout=3)
    opener = FakeOpener(ok_payload(True))
    InstagramClient(credentials, cfg, opener).set_lists_hidden(True)
    request, timeout = opener.calls[0]
    assert _form(opener)["client_doc_id"] == "42"
    assert request.get_header("X-ig-app-id") == "7"
    assert request.get_header("User-agent") == "UA/1"
    assert timeout == 3


@pytest.mark.parametrize(
    "payload",
    [
        ok_payload(False),  # asked to hide, got False
        json.dumps({"data": {}}).encode(),
        json.dumps({"errors": [{"message": "x"}], "data": {ROOT: {"value": True}}}).encode(),
        json.dumps({"status": "fail"}).encode(),
        json.dumps({"data": {ROOT: {"value": True, "error_name_value": "boom"}}}).encode(),
        json.dumps({"data": {ROOT: {"value": True}, f"{ROOT}(a)": {"value": True}}}).encode(),
    ],
)
def test_unconfirmed_changes_raise(credentials, payload: bytes) -> None:
    client = InstagramClient(credentials, opener=FakeOpener(payload))
    with pytest.raises(SettingNotConfirmedError):
        client.set_lists_hidden(True)


def test_unhide_requires_false_value(credentials) -> None:
    client = InstagramClient(credentials, opener=FakeOpener(ok_payload(True)))
    with pytest.raises(SettingNotConfirmedError):
        client.set_lists_hidden(False)


def test_http_error_is_redacted(credentials) -> None:
    leaked = json.dumps({"message": f"bad token {credentials.token}", "status": "fail"}).encode()
    error = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(leaked))
    client = InstagramClient(credentials, opener=FakeOpener(error=error))
    with pytest.raises(RequestError) as info:
        client.set_lists_hidden(True)
    text = str(info.value)
    assert text.startswith("HTTP 400:")
    assert credentials.token not in text
    assert SESSION_ID not in text
    assert "<REDACTED>" in text


def test_http_error_without_json_body(credentials) -> None:
    error = urllib.error.HTTPError("u", 500, "x", {}, io.BytesIO(b"<html>"))
    client = InstagramClient(credentials, opener=FakeOpener(error=error))
    with pytest.raises(RequestError, match="HTTP 500: No selected JSON error details"):
        client.set_lists_hidden(True)


@pytest.mark.parametrize("exc", [urllib.error.URLError("dns"), TimeoutError(), OSError("reset")])
def test_network_failures(credentials, exc: BaseException) -> None:
    client = InstagramClient(credentials, opener=FakeOpener(error=exc))
    with pytest.raises(RequestError, match="Network/TLS failure"):
        client.set_lists_hidden(True)


@pytest.mark.parametrize("payload", [b"not json", b"[1, 2]", b"\xff\xfe"])
def test_bad_bodies(credentials, payload: bytes) -> None:
    client = InstagramClient(credentials, opener=FakeOpener(payload))
    with pytest.raises(RequestError):
        client.set_lists_hidden(True)


def test_oversized_response(credentials) -> None:
    client = InstagramClient(credentials, opener=FakeOpener(b" " * (1024 * 1024 + 10)))
    with pytest.raises(RequestError, match="too large"):
        client.set_lists_hidden(True)


def test_redact_longest_first() -> None:
    assert redact("abc abcdef", {"abc", "abcdef"}) == "<REDACTED> <REDACTED>"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"doc_id": "abc"},
        {"app_id": ""},
        {"timeout": 0},
        {"timeout": 1000},
        {"user_agent": "bad\nagent"},
    ],
)
def test_invalid_config(kwargs) -> None:
    with pytest.raises(ConfigurationError):
        ClientConfig(**kwargs)


def test_config_from_env() -> None:
    cfg = ClientConfig.from_env({"IG_CLIENT_DOC_ID": "99", "IG_TIMEOUT": "5"})
    assert cfg.doc_id == "99"
    assert cfg.timeout == 5.0
    with pytest.raises(ConfigurationError):
        ClientConfig.from_env({"IG_TIMEOUT": "fast"})
