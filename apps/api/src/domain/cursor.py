"""Opaque keyset-pagination cursor over (created_at, id)."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from src.domain.errors import InvalidCursorError


@dataclass(frozen=True, slots=True)
class Cursor:
    created_at: datetime
    id: uuid.UUID

    def encode(self) -> str:
        payload = json.dumps({"t": self.created_at.isoformat(), "id": str(self.id)})
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")

    @classmethod
    def decode(cls, raw: str) -> Cursor:
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
            return cls(
                created_at=datetime.fromisoformat(payload["t"]),
                id=uuid.UUID(payload["id"]),
            )
        except (
            binascii.Error,
            json.JSONDecodeError,
            UnicodeDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise InvalidCursorError("Malformed pagination cursor") from exc
