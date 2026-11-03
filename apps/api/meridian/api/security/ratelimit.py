"""Fixed window rate limits with an in-process backend and a Valkey backend (shared across workers)."""

from __future__ import annotations

import threading
import time
from typing import Protocol

from meridian.api.errors import ProblemError


class Backend(Protocol):
    def incr(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Count for the key in the current window and seconds until the window ends."""

    def once(self, key: str, ttl_seconds: int) -> bool:
        """True the first time the key is seen within the ttl."""


class MemoryBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = {}

    def incr(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = time.monotonic()
        with self._lock:
            start, count = self._windows.get(key, (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            count += 1
            self._windows[key] = (start, count)
            if len(self._windows) > 50_000:
                self._windows = {k: v for k, v in self._windows.items() if now - v[0] < window_seconds}
            return count, max(1, int(window_seconds - (now - start)))

    def once(self, key: str, ttl_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            start, _ = self._windows.get(key, (0.0, 0))
            if start and now - start < ttl_seconds:
                return False
            self._windows[key] = (now, 1)
            return True

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()


class ValkeyBackend:
    def __init__(self, url: str) -> None:
        import valkey

        self.client = valkey.Valkey.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)

    def incr(self, key: str, window_seconds: int) -> tuple[int, int]:
        pipe = self.client.pipeline()
        pipe.incr(f"rl:{key}")
        pipe.ttl(f"rl:{key}")
        count, ttl = pipe.execute()  # type: ignore[no-untyped-call]
        if ttl < 0:
            self.client.expire(f"rl:{key}", window_seconds)
            ttl = window_seconds
        return int(count), int(ttl)

    def once(self, key: str, ttl_seconds: int) -> bool:
        return bool(self.client.set(f"once:{key}", "1", nx=True, ex=ttl_seconds))


_backend: Backend = MemoryBackend()


def configure(url: str | None) -> Backend:
    """Use Valkey when it is reachable; otherwise keep the in-process backend."""
    global _backend
    _backend = MemoryBackend()
    if url:
        try:
            candidate = ValkeyBackend(url)
            candidate.client.ping()
            _backend = candidate
        except Exception:  # noqa: BLE001 - any connection problem means the fallback is used
            _backend = MemoryBackend()
    return _backend


def backend() -> Backend:
    return _backend


def check(key: str, limit: int, window_seconds: int, *, detail: str = "Too many requests.") -> int:
    """Count one request and raise a 429 problem when the limit is exceeded. Returns the remaining allowance."""
    count, reset = _backend.incr(key, window_seconds)
    if count > limit:
        raise ProblemError(
            429,
            detail,
            code="rate-limited",
            headers={"Retry-After": str(reset), "X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0"},
        )
    return limit - count
