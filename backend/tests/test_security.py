"""Password hashing + JWT round-trip (no DB, no network).

Guards against the passlib/bcrypt incompatibility that made every signup 500:
passlib 1.7.4 raised on bcrypt 5.x during backend init, so `hash_password`
threw regardless of the password. The app now uses bcrypt directly.
"""

from __future__ import annotations

import uuid

from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_roundtrip():
    h = hash_password("hunter2")
    assert h.startswith("$2b$")  # bcrypt format, compatible with old hashes
    assert verify_password("hunter2", h)
    assert not verify_password("wrong-password", h)


def test_long_password_does_not_raise():
    # >72 bytes: bcrypt 5.x raises unless truncated. Must hash and verify, not 500.
    pw = "x" * 200
    h = hash_password(pw)
    assert verify_password(pw, h)
    # Truncation is consistent: the first 72 bytes verify the same hash.
    assert verify_password("x" * 72, h)


def test_verify_malformed_hash_returns_false():
    assert verify_password("anything", "not-a-valid-bcrypt-hash") is False


def test_jwt_roundtrip():
    uid = uuid.uuid4()
    token = create_access_token(uid)
    assert decode_access_token(token) == uid
    assert decode_access_token("garbage.token.value") is None
