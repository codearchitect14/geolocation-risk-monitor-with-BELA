"""Locust scenario: 50 concurrent users on the map and the dashboards.

    make perf-api           API with request limits raised (the limiter is tested elsewhere)
    make perf-seed          synthetic tenants, one with a manager account
    make perf-load          50 users, 60 second ramp, 5 minutes

Every user signs in with a password, keeps the session cookies, and repeats the calls the main screens make.
Data is synthetic. Environment: PERF_EMAIL, PERF_PASSWORD.
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

EMAIL = os.environ.get("PERF_EMAIL", "perf-manager@example.org")
PASSWORD = os.environ.get("PERF_PASSWORD", "perf passphrase 2026!")  # noqa: S105  (synthetic account on a local database)
API = "/api/v1"


class Operator(HttpUser):
    # Think time between actions. PERF_THINK=0 removes it to find the capacity of the service, not a realistic load.
    wait_time = between(0, 0) if os.environ.get("PERF_THINK") == "0" else between(1, 3)
    event_ids: list[str]

    def on_start(self) -> None:
        self.event_ids = []
        with self.client.post(
            f"{API}/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            name="POST /auth/login",
            catch_response=True,
        ) as res:
            if res.status_code != 200:
                res.failure(f"login failed: {res.status_code}")
                return
        listing = self.client.get(f"{API}/events?limit=200", name="GET /events (limit 200)").json()
        self.event_ids = [e["id"] for e in listing.get("items", [])]

    def asset_pages(self, pages: int) -> None:
        """Follow the cursor the way the map does when it loads every asset (200 per page)."""
        cursor = ""
        for _ in range(pages):
            res = self.client.get(f"{API}/assets?status=active&limit=200{cursor}", name="GET /assets (map page of 200)")
            token = res.json().get("next_cursor") if res.status_code == 200 else None
            if not token:
                return
            cursor = f"&cursor={token}"

    @task(5)
    def map_screen(self) -> None:
        """What the map page loads: incidents for the viewport, zones, alerts, then the asset pages."""
        self.client.get(f"{API}/events?limit=200&bbox=-125,24,-66,50&min_severity=2", name="GET /events (map viewport)")
        self.client.get(f"{API}/zones", name="GET /zones")
        self.client.get(f"{API}/alerts?limit=200", name="GET /alerts (limit 200)")
        self.asset_pages(pages=10)

    @task(4)
    def overview(self) -> None:
        self.client.get(f"{API}/events?limit=200", name="GET /events (limit 200)")
        self.client.get(f"{API}/alerts?limit=200", name="GET /alerts (limit 200)")
        self.client.get(f"{API}/analytics/operations", name="GET /analytics/operations")
        self.client.get(f"{API}/briefings?limit=3", name="GET /briefings")

    @task(3)
    def assets_list(self) -> None:
        self.client.get(f"{API}/assets?limit=100", name="GET /assets (page of 100)")

    @task(3)
    def incident(self) -> None:
        if self.event_ids:
            self.client.get(f"{API}/events/{random.choice(self.event_ids)}", name="GET /events/{id}")  # noqa: S311

    @task(1)
    def alert_queue(self) -> None:
        self.client.get(f"{API}/alerts?status=new&limit=50", name="GET /alerts (queue)")

    @task(1)
    def sources(self) -> None:
        self.client.get(f"{API}/sources", name="GET /sources")

    @task(1)
    def asset_search(self) -> None:
        self.client.get(f"{API}/assets?q=Site&limit=50", name="GET /assets (search)")

    @task(1)
    def place_search(self) -> None:
        q = random.choice(["Springfield", "Rotterdam", "Santos", "Chennai", "Osaka", "Leeds", "Lagos"])  # noqa: S311
        self.client.get(f"{API}/places/search?q={q}&limit=10", name="GET /places/search")
