"""Symmetric encryption for secrets at rest (TOTP seeds, webhook signing secrets)."""

from __future__ import annotations

from cryptography.fernet import Fernet

from meridian.api.settings import get_api_settings


def _fernet() -> Fernet:
    return Fernet(get_api_settings().fernet_key)


def encrypt(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt(value: bytes | memoryview) -> str:
    return _fernet().decrypt(bytes(value)).decode("utf-8")
