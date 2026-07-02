"""API-key hashing helper.

Keys are stored as SHA-256 digests so the raw key never touches the database;
the deterministic digest doubles as the unique lookup index.
"""

from __future__ import annotations

import hashlib


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
