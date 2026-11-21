"""Tests for session ID validation and header construction."""

from __future__ import annotations

import base64
import json

import pytest

from privacy import Credentials, InvalidSessionIdError

from .conftest import SESSION_ID


def test_valid_session_extracts_user_id() -> None:
    creds = Credentials.from_session_id(f"  {SESSION_ID}\n")
    assert creds.user_id == "12345678"
    assert creds.session_id == SESSION_ID


def test_url_encoded_colon_is_accepted() -> None:
    creds = Credentials.from_session_id("987%3Aabc%3A27%3Axyz")
    assert creds.user_id == "987"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "sessionid=12345:abc",
        "12345:abc;def",
        'abc"def',
        "has space:1",
        "0123:abc",
        "nodigits:abc",
        "12345",
        "12345:",
        "12345:ünicode",
    ],
)
def test_invalid_sessions_are_rejected(value: str) -> None:
    with pytest.raises(InvalidSessionIdError):
        Credentials.from_session_id(value)


def test_repr_does_not_leak_secret(credentials: Credentials) -> None:
    assert SESSION_ID not in repr(credentials)
    assert SESSION_ID not in str(credentials)


def test_authorization_header_round_trips(credentials: Credentials) -> None:
    assert credentials.authorization.startswith("Bearer IGT:2:")
    payload = json.loads(base64.b64decode(credentials.token))
    assert payload == {
        "ds_user_id": "12345678",
        "sessionid": SESSION_ID,
        "should_use_header_over_cookies": True,
    }


def test_cookie_header(credentials: Credentials) -> None:
    assert credentials.cookie == f"sessionid={SESSION_ID}; ds_user_id=12345678"
