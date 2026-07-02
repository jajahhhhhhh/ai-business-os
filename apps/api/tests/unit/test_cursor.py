"""Cursor encode/decode round-trip and tamper handling."""

import uuid
from datetime import UTC, datetime

import pytest

from src.domain.cursor import Cursor
from src.domain.errors import InvalidCursorError


def test_round_trip_preserves_fields() -> None:
    original = Cursor(
        created_at=datetime(2026, 7, 2, 12, 30, 45, 123456, tzinfo=UTC), id=uuid.uuid4()
    )
    decoded = Cursor.decode(original.encode())
    assert decoded == original


def test_encoded_cursor_is_opaque_ascii() -> None:
    token = Cursor(created_at=datetime.now(UTC), id=uuid.uuid4()).encode()
    assert token.isascii()
    assert " " not in token


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not-base64!!!",
        "aGVsbG8=",  # valid base64, not JSON
        "eyJmb28iOiAiYmFyIn0=",  # valid JSON, missing keys
    ],
)
def test_malformed_cursor_raises(raw: str) -> None:
    with pytest.raises(InvalidCursorError):
        Cursor.decode(raw)


def test_bad_uuid_in_cursor_raises() -> None:
    import base64
    import json

    payload = json.dumps({"t": datetime.now(UTC).isoformat(), "id": "not-a-uuid"})
    raw = base64.urlsafe_b64encode(payload.encode()).decode()
    with pytest.raises(InvalidCursorError):
        Cursor.decode(raw)
