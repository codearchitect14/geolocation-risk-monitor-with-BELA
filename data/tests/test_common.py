import hashlib
from pathlib import Path

import httpx
import pytest
import yaml

import common


def test_rate_limiter_waits_per_key() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = common.RateLimiter(5.0, clock=lambda: now[0], sleep=sleep)
    assert limiter.wait("a") == 0.0
    now[0] += 2.0
    assert limiter.wait("a") == pytest.approx(3.0)
    assert limiter.wait("b") == 0.0
    assert slept == [pytest.approx(3.0)]


def test_request_with_retry_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] < 3 else 200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = common.request_with_retry(client, "GET", "https://example.test/", sleep=lambda _: None)
    assert response.status_code == 200 and calls["n"] == 3


def test_request_with_retry_raises_after_limit() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        common.request_with_retry(client, "GET", "https://example.test/", retries=2, sleep=lambda _: None)


PAYLOAD = bytes(range(256)) * 400


def range_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "HEAD":
        return httpx.Response(200, headers={"Content-Length": str(len(PAYLOAD))})
    header = request.headers.get("Range")
    if header:
        start = int(header.split("=")[1].rstrip("-"))
        return httpx.Response(206, content=PAYLOAD[start:])
    return httpx.Response(200, content=PAYLOAD)


def test_download_resumes_partial_file(tmp_path: Path) -> None:
    dest = tmp_path / "file.bin"
    (tmp_path / "file.bin.part").write_bytes(PAYLOAD[:1000])
    client = httpx.Client(transport=httpx.MockTransport(range_handler))
    record = common.download_file(client, "https://example.test/file.bin", dest)
    assert dest.read_bytes() == PAYLOAD
    assert record["status"] == "downloaded"
    assert record["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    assert not (tmp_path / "file.bin.part").exists()


def test_download_skips_when_checksum_matches(tmp_path: Path) -> None:
    dest = tmp_path / "file.bin"
    dest.write_bytes(PAYLOAD)
    client = httpx.Client(transport=httpx.MockTransport(range_handler))
    record = common.download_file(
        client, "https://example.test/file.bin", dest, expected_sha256=hashlib.sha256(PAYLOAD).hexdigest()
    )
    assert record["status"] == "skipped"


def test_download_rejects_bad_checksum(tmp_path: Path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(range_handler))
    with pytest.raises(common.ChecksumError):
        common.download_file(client, "https://example.test/f", tmp_path / "f", expected_sha256="0" * 64)
    assert not (tmp_path / "f").exists()


def test_download_restarts_when_range_ignored(tmp_path: Path) -> None:
    (tmp_path / "f.part").write_bytes(b"stale-bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        return httpx.Response(200, content=PAYLOAD)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    common.download_file(client, "https://example.test/f", tmp_path / "f")
    assert (tmp_path / "f").read_bytes() == PAYLOAD


def test_record_files_and_harvest(tmp_path: Path) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text("# header\nsources:\n  - id: demo\n    kind: static\n", encoding="utf-8")
    artifact = {"path": str(common.data_dir() / "raw" / "a.txt"), "url": "u", "size": 3, "sha256": "ab"}
    common.record_files("demo", [artifact], manifest_file=manifest_file)
    loaded = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
    assert loaded["sources"][0]["files"][0]["path"] == "raw/a.txt"
    assert manifest_file.read_text(encoding="utf-8").startswith("# header")
    with pytest.raises(KeyError):
        common.record_files("nope", [], manifest_file=manifest_file)
    common.record_harvest("demo", {"written": 2}, manifest_file=manifest_file)
    assert yaml.safe_load(manifest_file.read_text(encoding="utf-8"))["sources"][0]["last_run"] == {"written": 2}


def test_write_status_tracks_failures() -> None:
    common.write_status("job", False, {"error": "x"})
    common.write_status("job", True, {"n": 1})
    state = common.read_json(common.status_dir() / "job.json")
    assert state["runs"] == 2 and state["failures"] == 1 and state["consecutive_failures"] == 0


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    assert common.append_jsonl(path, [{"a": "é"}, {"a": 2}]) == 2
    assert list(common.iter_jsonl(path)) == [{"a": "é"}, {"a": 2}]
