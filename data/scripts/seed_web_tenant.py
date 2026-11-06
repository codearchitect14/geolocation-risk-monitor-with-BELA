"""Seed the local web test tenant with illustrative assets placed near current events.

python data/scripts/seed_web_tenant.py [--tenant web-e2e] [--count 60]

Uploads through the public API as a manager so exposures, alerts and rules follow the normal paths.
Every asset name ends with "(illustrative)". Development use only.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

BASE = "http://127.0.0.1:8090/api/v1"
PASSWORD = "web-e2e passphrase 2026!"  # noqa: S105  (local test accounts only)
KINDS = ["site", "facility", "warehouse", "office", "port"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default="mgr@example.org")
    ap.add_argument("--count", type=int, default=60)
    args = ap.parse_args()
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(path: str, body: bytes | None = None, ctype: str = "application/json") -> dict[str, Any]:
        headers = {"Content-Type": ctype}
        csrf = next((c.value for c in jar if c.name == "ms_csrf"), None)
        if csrf:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(BASE + path, data=body, headers=headers)  # noqa: S310
        with opener.open(req) as r:
            result: dict[str, Any] = json.loads(r.read() or b"{}")
            return result

    call("/auth/login", json.dumps({"email": args.email, "password": PASSWORD}).encode())
    ids = move_recent_events()
    conn = connect_db()
    points: list[tuple[float, float]] = [
        (float(r[0]), float(r[1]))
        for r in conn.execute(
            "SELECT ST_Y(ST_PointOnSurface(geom)), ST_X(ST_PointOnSurface(geom)) "
            "FROM events WHERE id = ANY(%s::uuid[])",
            (ids,),
        ).fetchall()
    ]
    rng = random.Random(7)  # noqa: S311
    rows = ["name,lat,lon,city,country,criticality,type,external_id,tags"]
    for i in range(args.count):
        lat, lon = rng.choice(points)
        lat += rng.uniform(-0.35, 0.35)
        lon += rng.uniform(-0.45, 0.45)
        kind = rng.choice(KINDS)
        rows.append(
            f"{kind.title()} {i + 1:03d} (illustrative),{lat:.4f},{lon:.4f},,,{rng.randint(1, 5)},{kind},"
            f"WEB-{i + 1:03d},{rng.choice(['north', 'south', 'east', 'west'])}|{kind}"
        )
    boundary = "----seed"
    csv = "\n".join(rows).encode()
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="seed.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode()
        + csv
        + f"\r\n--{boundary}--\r\n".encode()
    )
    out = call("/uploads", body, f"multipart/form-data; boundary={boundary}")
    print(json.dumps({k: out.get(k) for k in ("status", "created", "rejected", "total_rows")}))
    refresh_exposures(ids)
    return 0


def connect_db() -> Any:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))
    from meridian.db import connect

    return connect()


def move_recent_events() -> list[str]:
    """Dev data is a few days old, so move the newest events to now. Returns their ids."""
    conn = connect_db()
    ids = [
        str(r[0])
        for r in conn.execute(
            "SELECT id FROM events WHERE status <> 'closed' AND geom IS NOT NULL ORDER BY last_seen_at DESC LIMIT 40"
        ).fetchall()
    ]
    conn.execute(
        "UPDATE events SET last_seen_at = now() - (random() * interval '30 hours') WHERE id = ANY(%s::uuid[])",
        (ids,),
    )
    conn.commit()
    return ids


def refresh_exposures(ids: list[str]) -> None:
    """Recompute exposures and alerts for the moved events, so new assets near them raise alerts."""
    import datetime as dt

    from meridian.events import service
    from meridian.events.config import load_events_config

    conn = connect_db()
    cfg = load_events_config()
    now = dt.datetime.now(dt.UTC)
    for event_id in ids:
        service.process_event(conn, cfg, event_id, now)
    conn.commit()
    print(f"recomputed {len(ids)} events")


if __name__ == "__main__":
    sys.exit(main())
