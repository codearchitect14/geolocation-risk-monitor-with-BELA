"""Argon2id password hashing and the password policy: length and estimated strength, no composition rules."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from zxcvbn import zxcvbn

from meridian.api.settings import get_api_settings

MIN_LENGTH = 12
MAX_LENGTH = 128
MIN_SCORE = 3


class PasswordPolicyError(ValueError):
    pass


def _hasher() -> PasswordHasher:
    if get_api_settings().argon2_fast:  # tests only: the policy and the algorithm are unchanged
        return PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def validate_password(password: str, user_inputs: list[str] | None = None) -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"The password must be at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"The password must be at most {MAX_LENGTH} characters.")
    result = zxcvbn(password[:72], user_inputs=[u for u in (user_inputs or []) if u])
    if result["score"] < MIN_SCORE:
        raise PasswordPolicyError("The password is too easy to guess. Use a longer passphrase of unrelated words.")


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(stored: str, password: str) -> bool:
    try:
        return _hasher().verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    """Spend comparable time when the account does not exist, so response time does not reveal it."""
    verify_password(_dummy_hash(), password)


_DUMMY: list[str] = []


def _dummy_hash() -> str:
    if not _DUMMY:
        _DUMMY.append(hash_password("not-a-real-account-password"))
    return _DUMMY[0]
