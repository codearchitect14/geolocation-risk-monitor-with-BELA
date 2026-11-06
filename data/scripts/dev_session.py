"""Sign in a local test account (enrolling an authenticator when required) and write a curl cookie jar.

python data/scripts/dev_session.py pa@example.org /tmp/pj

Secrets of the local test accounts are kept in .local/dev_mfa.json (git-ignored). Development use only.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any

import pyotp

BASE = "http://127.0.0.1:8090/api/v1"
PASSWORD = "web-e2e passphrase 2026!"  # noqa: S105  (local test accounts only)
STORE = Path(__file__).resolve().parents[2] / ".local" / "dev_mfa.json"


def main(email: str, jar_path: str) -> int:
    jar = MozillaCookieJar(jar_path)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    secrets = json.loads(STORE.read_text()) if STORE.exists() else {}

    def call(path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        csrf = next((c.value for c in jar if c.name == "ms_csrf"), None)
        if csrf:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=headers)  # noqa: S310
        with opener.open(req) as r:
            result: dict[str, Any] = json.loads(r.read() or b"{}")
            return result

    res = call("/auth/login", {"email": email, "password": PASSWORD})
    if res["status"] == "mfa_enrollment_required":
        setup = call("/auth/mfa/setup", {"setup_token": res["setup_token"]})
        secrets[email] = setup["secret"]
        STORE.write_text(json.dumps(secrets))
        call("/auth/mfa/verify", {"setup_token": res["setup_token"], "code": pyotp.TOTP(setup["secret"]).now()})
    elif res["status"] == "mfa_required":
        call("/auth/mfa/verify", {"mfa_token": res["mfa_token"], "code": pyotp.TOTP(secrets[email]).now()})
    jar.save(ignore_discard=True, ignore_expires=True)
    print("signed in", email)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
