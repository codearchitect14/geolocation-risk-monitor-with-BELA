"""Shared helpers for the data acquisition scripts.

Provides paths, logging, a rate limiter, retrying HTTP requests, resumable
checksum-verified downloads, atomic file writes, and manifest updates.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import logging
import os
import sys
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPTS_DIR.parent
CHUNK_SIZE = 1024 * 1024


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from the repository .env file without overriding the environment."""
    target = path or SCRIPTS_DIR.parent.parent / ".env"
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


def data_dir() -> Path:
    """Root of the dataset folder. Override with MS_DATA_DIR."""
    override = os.environ.get("MS_DATA_DIR", "").strip()
    return Path(override).expanduser().resolve() if override else DEFAULT_DATA_DIR


def raw_dir(*parts: str) -> Path:
    path = data_dir().joinpath("raw", *parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def processed_dir(*parts: str) -> Path:
    path = data_dir().joinpath("processed", *parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def manifest_path() -> Path:
    return DEFAULT_DATA_DIR / "manifest.yaml"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso_now() -> str:
    return utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def get_logger(name: str) -> logging.Logger:
    """Return a logger writing key=value style lines to stderr and data/logs/."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(os.environ.get("MS_LOG_LEVEL", "INFO").upper())
    fmt = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    fmt.converter = time.gmtime
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    try:
        log_dir = data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / f"{name}.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        logger.warning("file logging unavailable")
    logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# User agent and rate limiting
# ---------------------------------------------------------------------------


def user_agent(extra: str = "") -> str:
    contact = os.environ.get("MS_CONTACT", "").strip() or "contact-not-configured"
    base = f"MeridianSignal-data/0.1 (+{contact})"
    return f"{base} {extra}".strip()


class RateLimiter:
    """Enforce a minimum interval between calls, optionally per key (for example a domain)."""

    def __init__(self, min_interval: float, clock: Any = time.monotonic, sleep: Any = time.sleep):
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: str = "") -> float:
        """Block until the key may be used again. Returns the seconds slept."""
        with self._lock:
            now = self._clock()
            last = self._last.get(key)
            delay = 0.0 if last is None else max(0.0, last + self.min_interval - now)
            self._last[key] = now + delay
        if delay > 0:
            self._sleep(delay)
        return delay


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def make_client(
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 60.0,
    follow_redirects: bool = True,
) -> httpx.Client:
    merged = {"User-Agent": user_agent()}
    if headers:
        merged.update(headers)
    return httpx.Client(headers=merged, timeout=timeout, follow_redirects=follow_redirects)


def retry_delay(response: httpx.Response | None, attempt: int, base: float) -> float:
    if response is not None:
        value = response.headers.get("Retry-After")
        if value and value.isdigit():
            return float(min(int(value), 300))
    return float(min(base * (2**attempt), 120.0))


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 4,
    backoff: float = 2.0,
    sleep: Any = time.sleep,
    logger: logging.Logger | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request, retrying on transient statuses and network errors."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        response: httpx.Response | None = None
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code not in RETRY_STATUSES:
                return response
            last_error = httpx.HTTPStatusError(
                f"status {response.status_code}", request=response.request, response=response
            )
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_error = exc
        if attempt < retries:
            delay = retry_delay(response, attempt, backoff)
            if logger:
                logger.warning("retry %d/%d for %s in %.1fs: %s", attempt + 1, retries, url, delay, last_error)
            sleep(delay)
    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def append_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    """Append records as JSON lines. Returns the number written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


# ---------------------------------------------------------------------------
# Resumable, checksum-verified download
# ---------------------------------------------------------------------------


# Ask for unencoded bytes so Content-Length, ranges, and checksums describe the stored file.
IDENTITY = {"Accept-Encoding": "identity"}


class ChecksumError(RuntimeError):
    pass


def download_file(
    client: httpx.Client,
    url: str,
    dest: Path,
    *,
    expected_sha256: str | None = None,
    force: bool = False,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Download url to dest, resuming a partial file when the server supports ranges.

    An existing dest is kept when it matches expected_sha256, or, if no checksum is
    known, when its size equals the size reported by the server. The download is
    written to dest.part and renamed after the checksum passes.
    """
    log = logger or logging.getLogger("download")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    remote_size = _remote_size(client, url)
    if dest.exists() and not force:
        if expected_sha256:
            if sha256_file(dest) == expected_sha256:
                log.info("skip %s (checksum matches)", dest.name)
                return _artifact_record(dest, url, "skipped")
        elif remote_size is not None and dest.stat().st_size == remote_size:
            log.info("skip %s (size matches)", dest.name)
            return _artifact_record(dest, url, "skipped")

    resume_from = part.stat().st_size if part.exists() else 0
    if remote_size is not None and resume_from > remote_size:
        part.unlink()
        resume_from = 0
    headers = dict(IDENTITY)
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"

    with client.stream("GET", url, headers=headers) as response:
        if response.status_code == 416 and remote_size is not None and resume_from == remote_size:
            pass  # partial file is already complete
        else:
            if response.status_code == 200 and resume_from:
                log.info("server ignored range for %s, restarting", dest.name)
                resume_from = 0
            elif response.status_code not in (200, 206):
                response.raise_for_status()
            mode = "ab" if resume_from and response.status_code == 206 else "wb"
            with part.open(mode) as handle:
                for chunk in response.iter_bytes(CHUNK_SIZE):
                    handle.write(chunk)

    digest = sha256_file(part)
    if expected_sha256 and digest != expected_sha256:
        part.unlink()
        raise ChecksumError(f"{dest.name}: expected {expected_sha256}, got {digest}")
    if remote_size is not None and part.stat().st_size != remote_size:
        raise ChecksumError(f"{dest.name}: size {part.stat().st_size} differs from {remote_size}")
    os.replace(part, dest)
    log.info("downloaded %s (%d bytes)", dest.name, dest.stat().st_size)
    return _artifact_record(dest, url, "downloaded", digest)


def _remote_size(client: httpx.Client, url: str) -> int | None:
    try:
        response = client.head(url, headers=IDENTITY)
        value = response.headers.get("Content-Length")
        if response.status_code == 200 and value and value.isdigit():
            return int(value)
    except httpx.HTTPError:
        return None
    return None


def _artifact_record(path: Path, url: str, status: str, digest: str | None = None) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "url": url,
        "status": status,
        "size": path.stat().st_size,
        "sha256": digest or sha256_file(path),
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    target = path or manifest_path()
    with target.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("manifest must be a mapping")
    return loaded


def save_manifest(manifest: Mapping[str, Any], path: Path | None = None) -> None:
    target = path or manifest_path()
    header = ""
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.startswith("#"):
                break
            header += line + "\n"
    text = yaml.safe_dump(dict(manifest), sort_keys=False, allow_unicode=True, width=100)
    atomic_write_text(target, header + text)


def record_files(
    source_id: str,
    artifacts: Iterable[Mapping[str, Any]],
    *,
    manifest_file: Path | None = None,
) -> None:
    """Store size and checksum of downloaded files for a source in the manifest.

    Paths are saved relative to the data directory so the manifest is portable.
    """
    manifest = load_manifest(manifest_file)
    source = next((s for s in manifest["sources"] if s["id"] == source_id), None)
    if source is None:
        raise KeyError(f"unknown manifest source: {source_id}")
    root = data_dir()
    existing = {f["path"]: f for f in source.get("files") or []}
    for artifact in artifacts:
        rel = Path(artifact["path"])
        with contextlib.suppress(ValueError):
            rel = rel.relative_to(root)
        existing[rel.as_posix()] = {
            "path": rel.as_posix(),
            "url": artifact.get("url"),
            "size": artifact["size"],
            "sha256": artifact["sha256"],
        }
    source["files"] = sorted(existing.values(), key=lambda f: f["path"])
    source["retrieved_at"] = iso_now()
    save_manifest(manifest, manifest_file)


def record_harvest(source_id: str, stats: Mapping[str, Any], *, manifest_file: Path | None = None) -> None:
    """Update the retrieval timestamp and summary statistics for a harvested source."""
    manifest = load_manifest(manifest_file)
    source = next((s for s in manifest["sources"] if s["id"] == source_id), None)
    if source is None:
        raise KeyError(f"unknown manifest source: {source_id}")
    source["retrieved_at"] = iso_now()
    source["last_run"] = dict(stats)
    save_manifest(manifest, manifest_file)


# ---------------------------------------------------------------------------
# Job status (heartbeat files read by the scheduler report)
# ---------------------------------------------------------------------------


def status_dir() -> Path:
    return raw_dir("_status")


def write_status(job: str, ok: bool, detail: Mapping[str, Any] | None = None) -> None:
    path = status_dir() / f"{job}.json"
    state = read_json(path, {}) or {}
    now = iso_now()
    state["job"] = job
    state["runs"] = int(state.get("runs", 0)) + 1
    state["last_run"] = now
    if ok:
        state["last_success"] = now
        state["consecutive_failures"] = 0
    else:
        state["failures"] = int(state.get("failures", 0)) + 1
        state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
        state["last_error"] = dict(detail or {}) | {"at": now}
    if ok and detail:
        state["last_detail"] = dict(detail)
    state.setdefault("first_run", now)
    write_json(path, state)


def env_required(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set. {hint}")
    return value


def date_range(start: dt.date, end: dt.date, step_days: int = 1) -> Iterator[dt.date]:
    current = start
    while current <= end:
        yield current
        current += dt.timedelta(days=step_days)


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)
