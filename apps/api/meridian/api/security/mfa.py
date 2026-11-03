"""TOTP enrollment and verification, and single use recovery codes."""

from __future__ import annotations

import io
import secrets
import time

import pyotp
import segno

from meridian.api.security.tokens import sha256_hex

ISSUER_NAME = "Meridian Signal"
RECOVERY_CODE_COUNT = 10
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER_NAME)


def qr_svg(uri: str) -> str:
    buffer = io.BytesIO()
    segno.make(uri, error="m").save(buffer, kind="svg", scale=4, border=2, xmldecl=False, nl=False)
    return buffer.getvalue().decode("utf-8")


def verify_code(secret: str, code: str, at: float | None = None) -> int | None:
    """The accepted time step (for replay checks), or None. Allows one step of clock drift."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    now: float = at if at is not None else time.time()
    for offset in (0, -1, 1):
        moment = now + offset * totp.interval
        if secrets.compare_digest(totp.at(int(moment)), code):
            return int(moment // totp.interval)
    return None


def new_recovery_codes() -> list[str]:
    def one() -> str:
        return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(4))

    return [one() for _ in range(RECOVERY_CODE_COUNT)]


def hash_recovery_code(code: str) -> str:
    return sha256_hex(code.strip().upper().replace(" ", ""))
