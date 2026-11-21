"""Shared fixtures and test doubles."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from privacy import Credentials

SESSION_ID = "12345678:AbCdEf123456:27:AYhxyz"
ROOT = "xdt_api__v1__settings__set_bool"


class FakeResponse:
    """Minimal context-manager response."""

    def __init__(self, payload: bytes) -> None:
        self._buffer = io.BytesIO(payload)

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class FakeOpener:
    """Records requests and returns a canned payload or raises a canned error."""

    def __init__(self, payload: bytes = b"{}", error: BaseException | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[tuple[Any, float]] = []

    def open(self, request: Any, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        return FakeResponse(self.payload)


def ok_payload(value: bool, key: str = ROOT) -> bytes:
    return json.dumps({"data": {key: {"value": value}}}).encode()


@pytest.fixture
def credentials() -> Credentials:
    return Credentials.from_session_id(SESSION_ID)
