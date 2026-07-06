"""Envelope encryption for BYOK provider keys.

Scheme: a fresh 256-bit **data key (DEK)** is generated per record and used to
AES-GCM-encrypt the provider key. The DEK is then wrapped (AES-GCM) under the
application **master key** (`ABOS_MASTER_KEY`, 32 bytes base64url). Only the
wrapped DEK and ciphertext are stored; plaintext keys never touch the database
and are decrypted only transiently inside the provider layer.

In production the master key would live in a KMS/HSM; here it is an env var,
which keeps the same envelope structure and swap-in path.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


class MasterKeyError(RuntimeError):
    """Raised when the master key is missing or malformed."""


def _master_key() -> bytes:
    raw = settings.master_key
    if not raw:
        raise MasterKeyError(
            "ABOS_MASTER_KEY is not set. Generate one with `make gen-key`."
        )
    try:
        key = base64.urlsafe_b64decode(raw)
    except Exception as exc:  # noqa: BLE001
        raise MasterKeyError("ABOS_MASTER_KEY is not valid base64url.") from exc
    if len(key) != 32:
        raise MasterKeyError("ABOS_MASTER_KEY must decode to exactly 32 bytes.")
    return key


@dataclass(frozen=True)
class SealedSecret:
    """The three stored components of an envelope-encrypted secret."""

    ciphertext: bytes
    wrapped_data_key: bytes
    nonce: bytes


def seal(plaintext: str) -> SealedSecret:
    """Encrypt ``plaintext`` (a provider key) for storage."""
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext.encode("utf-8"), None)

    # Wrap the DEK under the master key with its own nonce, prepended to the blob.
    wrap_nonce = os.urandom(12)
    wrapped = wrap_nonce + AESGCM(_master_key()).encrypt(wrap_nonce, data_key, None)
    return SealedSecret(ciphertext=ciphertext, wrapped_data_key=wrapped, nonce=nonce)


def open_secret(sealed: SealedSecret) -> str:
    """Decrypt a stored secret back to plaintext. Caller must not log the result."""
    wrap_nonce, wrapped = sealed.wrapped_data_key[:12], sealed.wrapped_data_key[12:]
    data_key = AESGCM(_master_key()).decrypt(wrap_nonce, wrapped, None)
    plaintext = AESGCM(data_key).decrypt(sealed.nonce, sealed.ciphertext, None)
    return plaintext.decode("utf-8")


def fingerprint(plaintext: str) -> str:
    """Non-reversible display token, e.g. ``sk-…a1b2`` (prefix + last 4)."""
    prefix = plaintext[:3]
    tail = plaintext[-4:] if len(plaintext) >= 4 else "????"
    return f"{prefix}…{tail}"
