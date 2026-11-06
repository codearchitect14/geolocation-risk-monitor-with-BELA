"""Bulk scenarios for the performance report: tenant seeding, exposure recomputation at scale, and asset upload.

    python infra/perf/bulk_load.py seed --tenants 100 --assets 500     synthetic tenants (slug prefix perf-)
    python infra/perf/bulk_load.py recompute                           exposure recomputation over every perf tenant
    python infra/perf/bulk_load.py upload --rows 10000                 CSV upload through the API
    python infra/perf/bulk_load.py cleanup                             remove everything the seed created

All data is synthetic and labeled. Development database only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import time
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from meridian.api.security.passwords import hash_password  # noqa: E402
from meridian.db import connect  # noqa: E402
from meridian.events import service  # noqa: E402
from meridian.events.config import load_events_config  # noqa: E402

PREFIX = "perf-"
LARGE = "perf-large"
EMAIL = "perf-manager@example.org"
PASSWORD = "perf passphrase 2026!"  # noqa: S105  (synthetic account on a local database)
BASE = "http://127.0.0.1:8090/api/v1"


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


def summary(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "p50": round(pct(values, 50), 3),
        "p95": round(pct(values, 95), 3),
        "max": round(max(values), 3),
    }


def seed(tenants: int, assets: int, large: int) -> None:
    import random

    conn = connect()
    rng = random.Random(11)  # noqa: S311  (synthetic placement)
    pool = conn.execute(
        """SELECT lat, lon, country_code FROM places
            WHERE type IN ('city', 'town') AND population >= 100000 AND lat IS NOT NULL ORDER BY id"""
    ).fetchall()
    cleanup(conn)

    def add_tenant(slug: str, count: int) -> None:
        row = conn.execute(
            "INSERT INTO tenants (name, slug, industry, is_demo) VALUES (%s, %s, 'illustrative', true) RETURNING id",
            (f"Performance test {slug} (synthetic data)", slug),
        ).fetchone()
        assert row is not None
        with conn.cursor().copy(
            "COPY assets (tenant_id, name, type, geom, criticality, country_code, tags, external_id) FROM STDIN"
        ) as copy:
            for i in range(count):
                lat, lon, cc = rng.choice(pool)
                lat = max(-85.0, min(85.0, lat + rng.uniform(-0.3, 0.3)))
                lon = max(-179.0, min(179.0, lon + rng.uniform(-0.4, 0.4)))
                copy.write_row(
                    (row[0], f"Site {i + 1:05d} (synthetic)", "site", f"SRID=4326;POINT({lon:.5f} {lat:.5f})",
                     rng.randint(1, 5), cc, "{synthetic}", f"PF-{i + 1:05d}")
                )  # fmt: skip

    started = time.perf_counter()
    for n in range(1, tenants + 1):
        add_tenant(f"{PREFIX}{n:03d}", assets)
    add_tenant(LARGE, large)
    tenant_id = conn.execute("SELECT id FROM tenants WHERE slug = %s", (LARGE,)).fetchone()
    assert tenant_id is not None
    conn.execute(
        "INSERT INTO users (tenant_id, email, display_name, password_hash, role) "
        "VALUES (%s, %s, 'Performance manager', %s, 'manager')",
        (tenant_id[0], EMAIL, hash_password(PASSWORD)),
    )
    conn.commit()
    conn.execute("ANALYZE assets")
    total = conn.execute(
        "SELECT count(*) FROM assets a JOIN tenants t ON t.id = a.tenant_id WHERE t.slug LIKE 'perf-%'"
    ).fetchone()
    print(
        json.dumps(
            {
                "tenants": tenants + 1,
                "assets": total[0] if total else 0,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
    )


def cleanup(conn: Any = None) -> None:
    own = conn is None
    conn = conn or connect()
    conn.execute("DELETE FROM users WHERE email = %s", (EMAIL,))
    deleted = conn.execute("DELETE FROM tenants WHERE slug LIKE %s", (PREFIX + "%",)).rowcount
    conn.commit()
    if own:
        print(json.dumps({"tenants_deleted": deleted}))


def recompute(events: int) -> None:
    """Move the newest events to now, then recompute exposures: once for every tenant, and once per tenant."""
    conn = connect()
    cfg = load_events_config()
    now = dt.datetime.now(dt.UTC)
    ids = [
        str(r[0])
        for r in conn.execute(
            "SELECT id FROM events WHERE status <> 'closed' AND geom IS NOT NULL ORDER BY last_seen_at DESC LIMIT %s",
            (events,),
        ).fetchall()
    ]
    conn.execute(
        "UPDATE events SET last_seen_at = now() - (random() * interval '30 hours') WHERE id = ANY(%s::uuid[])", (ids,)
    )
    conn.commit()
    perf = [
        str(r[0])
        for r in conn.execute("SELECT id FROM tenants WHERE slug LIKE %s ORDER BY slug", (PREFIX + "%",)).fetchall()
    ]
    assets = conn.execute(
        "SELECT count(*) FROM assets a JOIN tenants t ON t.id = a.tenant_id WHERE t.slug LIKE %s", (PREFIX + "%",)
    ).fetchone()
    per_event: list[float] = []
    started = time.perf_counter()
    for event_id in ids:
        t0 = time.perf_counter()
        service.process_event(conn, cfg, event_id, now)
        conn.commit()
        per_event.append(time.perf_counter() - t0)
    full_pass = time.perf_counter() - started

    from meridian.events import exposure

    per_tenant: list[float] = []
    started = time.perf_counter()
    for tenant in perf:
        t0 = time.perf_counter()
        for event_id in ids:
            exposure.compute_for_event(conn, cfg, event_id, now, tenant_id=tenant)
        conn.commit()
        per_tenant.append(time.perf_counter() - t0)
    tenant_pass = time.perf_counter() - started
    stored = conn.execute(
        "SELECT count(*) FROM exposures x JOIN tenants t ON t.id = x.tenant_id WHERE t.slug LIKE %s", (PREFIX + "%",)
    ).fetchone()
    print(
        json.dumps(
            {
                "events": len(ids),
                "perf_tenants": len(perf),
                "perf_assets": assets[0] if assets else 0,
                "exposures_stored": stored[0] if stored else 0,
                "all_tenants_one_pass_seconds": round(full_pass, 2),
                "per_event_seconds": summary(per_event),
                "tenant_by_tenant_pass_seconds": round(tenant_pass, 2),
                "per_tenant_seconds": summary(per_tenant),
            },
            indent=2,
        )
    )


def upload(rows: int, chunk: int, repeat: int) -> None:
    import random

    rng = random.Random(5)  # noqa: S311
    run = int(time.time())
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(path: str, body: bytes, ctype: str = "application/json") -> dict[str, Any]:
        headers = {"Content-Type": ctype}
        csrf = next((c.value for c in jar if c.name == "ms_csrf"), None)
        if csrf:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(BASE + path, data=body, headers=headers)  # noqa: S310
        with opener.open(req, timeout=600) as r:  # noqa: S310
            result: dict[str, Any] = json.loads(r.read() or b"{}")
            return result

    call("/auth/login", json.dumps({"email": EMAIL, "password": PASSWORD}).encode())

    def send(batch: int, tag: str) -> tuple[float, dict[str, Any]]:
        out = io.StringIO()
        out.write("name,lat,lon,city,country,criticality,type,external_id,tags\n")
        for i in range(batch):
            lat, lon = rng.uniform(-50, 60), rng.uniform(-120, 140)
            ident = f"{run}-{tag}-{i:05d}"  # new external ids on every run, so rows are created rather than updated
            out.write(
                f"Upload {ident} (synthetic),{lat:.4f},{lon:.4f},,,{rng.randint(1, 5)},site,UP-{ident},synthetic\n"
            )
        boundary = "----perf"
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="perf.csv"\r\n'
                "Content-Type: text/csv\r\n\r\n"
            ).encode()
            + out.getvalue().encode()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        t0 = time.perf_counter()
        res = call("/uploads", body, f"multipart/form-data; boundary={boundary}")
        return time.perf_counter() - t0, res

    times: list[float] = []
    created = 0
    started = time.perf_counter()
    for n in range(0, rows, chunk):
        seconds, res = send(min(chunk, rows - n), f"bulk{n}")
        times.append(seconds)
        created += int(res.get("rows_accepted") or 0)
    whole = time.perf_counter() - started
    small: list[float] = []
    for r in range(repeat):
        seconds, _ = send(1000, f"small{r}")
        small.append(seconds)
    print(
        json.dumps(
            {
                "rows": rows,
                "chunk_rows": chunk,
                "rows_accepted": created,
                "total_seconds": round(whole, 2),
                "rows_per_second": round(rows / whole),
                "per_request_seconds": summary(times),
                "uploads_of_1000_rows_seconds": summary(small),
            },
            indent=2,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--tenants", type=int, default=100)
    s.add_argument("--assets", type=int, default=500)
    s.add_argument("--large", type=int, default=5000)
    r = sub.add_parser("recompute")
    r.add_argument("--events", type=int, default=40)
    u = sub.add_parser("upload")
    u.add_argument("--rows", type=int, default=10000)
    u.add_argument("--chunk", type=int, default=5000)
    u.add_argument("--repeat", type=int, default=10)
    sub.add_parser("cleanup")
    args = ap.parse_args()
    if args.cmd == "seed":
        seed(args.tenants, args.assets, args.large)
    elif args.cmd == "recompute":
        recompute(args.events)
    elif args.cmd == "upload":
        upload(args.rows, args.chunk, args.repeat)
    else:
        cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
