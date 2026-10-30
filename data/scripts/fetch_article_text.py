"""Fetch article pages for linking and store metadata plus a short snippet.

Safety and policy controls: robots.txt is honored, requests carry a contact
User-Agent, each domain is rate limited, private and link-local addresses are
blocked (also across redirects), response size and time are capped, and the
language is detected with lingua. Only a snippet of at most 300 characters is
written to disk. Full article text is returned to the caller in memory for
linking and is never persisted by this script.
"""

from __future__ import annotations

import argparse
import dataclasses
import ipaddress
import socket
import sys
import time
import urllib.robotparser
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

import common

SNIPPET_CHARS = 300
MAX_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5
DEFAULT_DOMAIN_INTERVAL = 3.0
ROBOTS_TTL_SECONDS = 6 * 3600
DETECT_LANGUAGES = [
    "ENGLISH",
    "SPANISH",
    "FRENCH",
    "GERMAN",
    "PORTUGUESE",
    "ITALIAN",
    "RUSSIAN",
    "ARABIC",
    "CHINESE",
    "JAPANESE",
    "KOREAN",
    "HINDI",
    "TURKISH",
    "INDONESIAN",
    "DUTCH",
    "POLISH",
    "UKRAINIAN",
    "SWAHILI",
    "URDU",
    "BENGALI",
    "PERSIAN",
    "VIETNAMESE",
    "THAI",
    "GREEK",
]

log = common.get_logger("fetch_article_text")


class BlockedError(RuntimeError):
    pass


@dataclasses.dataclass
class FetchedArticle:
    url: str
    final_url: str
    status: str
    http_status: int | None = None
    title: str | None = None
    text: str | None = None  # in memory only
    language: str | None = None
    language_confidence: float | None = None
    fetched_at: str = ""

    def to_record(self) -> dict[str, Any]:
        """Persistable form: metadata and a snippet, never the full text."""
        text = self.text or ""
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "http_status": self.http_status,
            "title": self.title,
            "snippet": " ".join(text.split())[:SNIPPET_CHARS] or None,
            "text_chars": len(text),
            "language": self.language,
            "language_confidence": self.language_confidence,
            "fetched_at": self.fetched_at,
        }


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def default_resolver(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)]


def check_url(url: str, resolver: Callable[[str], list[str]] = default_resolver) -> None:
    """Raise BlockedError unless the URL is http(s) and resolves only to public addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BlockedError("unsupported scheme or host")
    try:
        addresses = [parsed.hostname] if _is_ip(parsed.hostname) else resolver(parsed.hostname)
    except OSError as exc:
        raise BlockedError(f"dns failure: {exc}") from exc
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise BlockedError("address is not public")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class LanguageDetector:
    """Lazy lingua wrapper so importing this module stays cheap."""

    def __init__(self) -> None:
        self._detector: Any = None

    def detect(self, text: str) -> tuple[str | None, float | None]:
        if len(text) < 40:
            return None, None
        if self._detector is None:
            from lingua import Language, LanguageDetectorBuilder

            languages = [getattr(Language, name) for name in DETECT_LANGUAGES]
            self._detector = LanguageDetectorBuilder.from_languages(*languages).build()
        sample = text[:2000]
        best = self._detector.compute_language_confidence_values(sample)
        if not best:
            return None, None
        top = best[0]
        return top.language.iso_code_639_1.name.lower(), round(float(top.value), 4)


class ArticleFetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        domain_interval: float = DEFAULT_DOMAIN_INTERVAL,
        resolver: Callable[[str], list[str]] = default_resolver,
        detector: LanguageDetector | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client or common.make_client(timeout=30.0, follow_redirects=False)
        self.limiter = common.RateLimiter(domain_interval, sleep=sleep)
        self.resolver = resolver
        self.detector = detector or LanguageDetector()
        self._robots: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}
        self._agent = self.client.headers.get("User-Agent", "MeridianSignal-data")

    def allowed_by_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        cached = self._robots.get(origin)
        if cached is None or time.monotonic() - cached[0] > ROBOTS_TTL_SECONDS:
            parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            try:
                response = self._get_robots(origin + "/robots.txt")
                if response.status_code in (401, 403):
                    parser.disallow_all = True  # type: ignore[union-attr]
                elif response.status_code >= 400:
                    parser.allow_all = True  # type: ignore[union-attr]
                else:
                    parser.parse(response.text.splitlines())  # type: ignore[union-attr]
            except (httpx.HTTPError, BlockedError):
                parser = None  # robots unavailable: be conservative and skip the site
            self._robots[origin] = (time.monotonic(), parser)
            cached = self._robots[origin]
        parser = cached[1]
        return bool(parser and parser.can_fetch(self._agent, url))

    def _get_robots(self, url: str) -> httpx.Response:
        """Fetch robots.txt, following a few redirects with the same address checks."""
        response = httpx.Response(404)
        for _ in range(4):
            check_url(url, self.resolver)
            self.limiter.wait(urlparse(url).netloc)
            response = self.client.get(url)
            if not (response.is_redirect and response.headers.get("location")):
                break
            url = urljoin(url, response.headers["location"])
        return response

    def _get_limited(self, url: str) -> tuple[httpx.Response, bytes]:
        """GET with manual redirects, SSRF checks, and a body size cap."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current, self.resolver)
            self.limiter.wait(urlparse(current).netloc)
            with self.client.stream("GET", current, headers={"Accept": "text/html,*/*;q=0.5"}) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise BlockedError("response too large")
                return resp, bytes(body)
        raise BlockedError("too many redirects")

    def fetch(self, url: str) -> FetchedArticle:
        result = FetchedArticle(url=url, final_url=url, status="error", fetched_at=common.iso_now())
        try:
            check_url(url, self.resolver)
            if not self.allowed_by_robots(url):
                result.status = "robots_disallowed"
                return result
            response, body = self._get_limited(url)
        except BlockedError as exc:
            result.status = f"blocked: {exc}"
            return result
        except httpx.HTTPError as exc:
            result.status = f"network_error: {type(exc).__name__}"
            return result
        result.final_url = str(response.url)
        result.http_status = response.status_code
        if response.status_code != 200:
            result.status = f"http_{response.status_code}"
            return result
        self._extract(result, body, response.headers.get("content-type", ""))
        return result

    def _extract(self, result: FetchedArticle, body: bytes, content_type: str) -> None:
        if "html" not in content_type and "xml" not in content_type:
            result.status = "unsupported_content_type"
            return
        import trafilatura

        html = body.decode(_charset(content_type), errors="replace")
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        meta = trafilatura.extract_metadata(html)
        result.title = getattr(meta, "title", None) if meta else None
        if not text:
            result.status = "no_text"
            return
        result.text = text
        result.language, result.language_confidence = self.detector.detect(text)
        result.status = "ok"


def _charset(content_type: str) -> str:
    for part in content_type.split(";"):
        part = part.strip().lower()
        if part.startswith("charset="):
            return part.split("=", 1)[1].strip() or "utf-8"
    return "utf-8"


def iter_input_urls(paths: list[Path]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for record in common.iter_jsonl(path):
            url = record.get("url")
            if isinstance(url, str) and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="*", type=Path, help="JSONL files with a url field")
    parser.add_argument("--url", action="append", default=[], help="fetch a single URL")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--domain-interval", type=float, default=DEFAULT_DOMAIN_INTERVAL)
    parser.add_argument("--out", type=Path, help="output JSONL (default: raw/news/articles/<date>.jsonl)")
    args = parser.parse_args(argv)

    urls = args.url + iter_input_urls(args.inputs)
    if not urls:
        parser.error("provide --url or at least one input JSONL")
    out = args.out or common.raw_dir("news", "articles") / f"{common.iso_now()[:10]}.jsonl"
    done = {r["url"] for r in common.iter_jsonl(out)} if out.exists() else set()
    todo = [u for u in urls if u not in done][: args.limit]

    fetcher = ArticleFetcher(domain_interval=args.domain_interval)
    counts: dict[str, int] = {}
    for url in todo:
        article = fetcher.fetch(url)
        common.append_jsonl(out, [article.to_record()])
        key = article.status.split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    log.info("fetched %d urls: %s", len(todo), counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
