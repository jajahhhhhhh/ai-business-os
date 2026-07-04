"""Application-layer PII encryption for leads.contact_json (M5, §8.5).

Fernet (AES-128-CBC + HMAC, `cryptography` core dep) encrypts the PDPA-
minimized contact record {platform, handle, url} before it is written to the
jsonb column; the stored shape is {"enc": "<fernet token>"}.

Key resolution:
1. settings.pii_encryption_key (env PII_ENCRYPTION_KEY) — either a proper
   Fernet key (urlsafe base64, 32 bytes) or any passphrase (derived via
   sha256 -> urlsafe b64).
2. Empty -> DERIVED from settings.api_secret_key (sha256 -> urlsafe b64) with
   a warning logged once per process: rotation of api_secret_key then also
   rotates the PII key, so a dedicated PII_ENCRYPTION_KEY is recommended.

decrypt_contact is tolerant by design: None, legacy plaintext dicts (rows
written before M5) and undecryptable tokens never raise — they return the
legacy dict or None so a lost key can never take down the leads API.

NOTE: ARCHITECTURE.md §14 names pgcrypto for PII columns; this is app-layer
encryption instead (tracked in docs/tech-debt.md).
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken

from src.config import Settings

logger = structlog.get_logger("infrastructure.pii")

ENC_FIELD = "enc"

# Warn-once bookkeeping (per process) for the derived-key path.
_warned_derived = False


def derive_key(secret: str) -> bytes:
    """Any string -> a valid urlsafe-base64 32-byte Fernet key."""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def _warn_derived_once() -> None:
    global _warned_derived
    if not _warned_derived:
        _warned_derived = True
        logger.warning(
            "pii_encryption_key_missing",
            detail=(
                "PII_ENCRYPTION_KEY is not set; deriving the leads contact "
                "encryption key from API_SECRET_KEY. Set a dedicated "
                "PII_ENCRYPTION_KEY so secret rotation does not orphan "
                "encrypted contacts."
            ),
        )


def reset_warning_for_tests() -> None:
    """Test hook: forget the warn-once flag."""
    global _warned_derived
    _warned_derived = False


class PiiCipher:
    """Encrypt/decrypt the lead contact payload. Cheap to construct."""

    def __init__(self, key: str, *, fallback_secret: str = "") -> None:
        self.key_derived = not key
        if key:
            try:
                self._fernet = Fernet(key.encode("utf-8"))
            except (ValueError, TypeError):
                # A passphrase rather than a Fernet key: derive deterministically.
                self._fernet = Fernet(derive_key(key))
        else:
            _warn_derived_once()
            self._fernet = Fernet(derive_key(fallback_secret))

    @classmethod
    def from_settings(cls, settings: Settings) -> PiiCipher:
        return cls(settings.pii_encryption_key, fallback_secret=settings.api_secret_key)

    def encrypt_contact(self, contact: dict[str, Any] | None) -> dict[str, Any] | None:
        if contact is None:
            return None
        token = self._fernet.encrypt(
            json.dumps(contact, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        return {ENC_FIELD: token.decode("ascii")}

    def decrypt_contact(self, value: object) -> dict[str, Any] | None:
        """Tolerant decrypt: None/legacy/undecryptable never raise."""
        if not isinstance(value, dict):
            return None
        token = value.get(ENC_FIELD)
        if token is None:
            # Legacy plaintext contact written before M5 encryption.
            return value
        if not isinstance(token, str):
            return None
        try:
            data = self._fernet.decrypt(token.encode("ascii"))
            decoded = json.loads(data.decode("utf-8"))
        except (InvalidToken, ValueError, UnicodeError):
            logger.warning("pii_contact_undecryptable")
            return None
        return decoded if isinstance(decoded, dict) else None
