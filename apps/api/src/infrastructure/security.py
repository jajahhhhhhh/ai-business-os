"""API-key hashing helpers.

Keys are stored as SHA-256 digests so the raw key never touches the database;
the deterministic digest doubles as the lookup index.
"""

from __future__ import annotations

import hashlib
import hmac


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(raw_key), stored_hash)
