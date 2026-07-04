"""M5 PII encryption for leads.contact_json (src/infrastructure/pii.py)."""

from __future__ import annotations

import pytest
import structlog.testing
from cryptography.fernet import Fernet

from src.infrastructure import pii
from src.infrastructure.pii import ENC_FIELD, PiiCipher, derive_key

CONTACT = {"platform": "reddit", "handle": "u/somchai", "url": "https://reddit.com/r/x/1"}


@pytest.fixture(autouse=True)
def _reset_warn_once() -> None:
    pii.reset_warning_for_tests()


def test_roundtrip_with_explicit_fernet_key() -> None:
    cipher = PiiCipher(Fernet.generate_key().decode())
    stored = cipher.encrypt_contact(CONTACT)
    assert stored is not None and set(stored) == {ENC_FIELD}
    assert isinstance(stored[ENC_FIELD], str)
    assert cipher.decrypt_contact(stored) == CONTACT


def test_roundtrip_with_passphrase_key() -> None:
    """A non-Fernet passphrase is derived instead of rejected."""
    cipher = PiiCipher("not-a-fernet-key")
    stored = cipher.encrypt_contact(CONTACT)
    assert PiiCipher("not-a-fernet-key").decrypt_contact(stored) == CONTACT
    assert cipher.key_derived is False  # an explicit key was configured


def test_empty_key_derives_from_api_secret_with_warning() -> None:
    with structlog.testing.capture_logs() as logs:
        cipher = PiiCipher("", fallback_secret="api-secret")
    assert cipher.key_derived is True
    assert any(log["event"] == "pii_encryption_key_missing" for log in logs)
    # Same derivation is stable across instances (restart interop).
    stored = cipher.encrypt_contact(CONTACT)
    assert PiiCipher("", fallback_secret="api-secret").decrypt_contact(stored) == CONTACT


def test_derived_key_warning_fires_once_per_process() -> None:
    with structlog.testing.capture_logs() as logs:
        PiiCipher("", fallback_secret="s")
        PiiCipher("", fallback_secret="s")
    assert sum(1 for log in logs if log["event"] == "pii_encryption_key_missing") == 1


def test_encrypt_none_is_none() -> None:
    assert PiiCipher("k").encrypt_contact(None) is None


def test_decrypt_is_tolerant_of_null_and_legacy_values() -> None:
    cipher = PiiCipher("k")
    assert cipher.decrypt_contact(None) is None
    assert cipher.decrypt_contact("not-a-dict") is None
    # Legacy plaintext contact rows (pre-M5) pass through unchanged.
    legacy = {"platform": "reddit", "handle": "u/old"}
    assert cipher.decrypt_contact(legacy) == legacy


def test_decrypt_garbage_token_returns_none() -> None:
    cipher = PiiCipher("k")
    assert cipher.decrypt_contact({ENC_FIELD: "garbage-token"}) is None
    assert cipher.decrypt_contact({ENC_FIELD: 123}) is None


def test_decrypt_with_wrong_key_returns_none() -> None:
    stored = PiiCipher("key-one").encrypt_contact(CONTACT)
    assert PiiCipher("key-two").decrypt_contact(stored) is None


def test_derive_key_is_a_valid_fernet_key() -> None:
    Fernet(derive_key("anything"))  # does not raise
    assert derive_key("a") != derive_key("b")
