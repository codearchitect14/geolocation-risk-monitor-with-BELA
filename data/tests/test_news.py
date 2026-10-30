import gzip
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

import common
import download_gkg
import fetch_article_text as fat
import harvest_gdelt

# Real GKG 2.1 V2EnhancedLocations layout: type#name#country#adm1#adm2#lat#lon#feature#offset
V2_LOCATIONS = (
    "1#Chilean#CI#CI##-30#-71#CI#854;"
    "4#Tokyo, Tokyo, Japan#JA#JA40#36340#35.685#139.751#-246227#5;"
    "3#Springfield, Illinois, United States#US#USIL#17167#39.80#-89.64#1234#99;"
    "4#Nowhere#XX#XX##999#10#77#12;"
    "bad#block"
)


def test_parse_v2_locations() -> None:
    locations = download_gkg.parse_v2_locations(V2_LOCATIONS)
    assert [loc["type"] for loc in locations] == ["country", "world_city", "us_city", "world_city"]
    tokyo = locations[1]
    assert (tokyo["adm1_code"], tokyo["adm2_code"], tokyo["feature_id"], tokyo["offset"]) == (
        "JA40",
        "36340",
        "-246227",
        5,
    )
    assert (tokyo["lat"], tokyo["lon"]) == (35.685, 139.751)
    assert locations[3]["lat"] is None  # out of range latitude is dropped


def make_gkg_line(url: str, locations: str, translation: str = "") -> str:
    cols = [""] * 27
    cols[0], cols[1], cols[2], cols[3], cols[4] = "20261030121500-1", "20261030121500", "1", "example.test", url
    cols[10], cols[25] = locations, translation
    return "\t".join(cols) + "\n"


def test_iter_gkg_records_filters_rows() -> None:
    lines = [
        make_gkg_line("https://example.test/a", V2_LOCATIONS, "srclc:fra; eng:Moses 2.1.1"),
        make_gkg_line("https://example.test/b", ""),
        "short\tline\n",
        make_gkg_line("ftp://example.test/c", V2_LOCATIONS),
    ]
    records = list(download_gkg.iter_gkg_records(iter(lines)))
    assert len(records) == 1
    assert records[0]["source_language"] == "fra" and records[0]["translated"] is True


def test_convert_zip(tmp_path: Path) -> None:
    archive = tmp_path / "20261030121500.gkg.csv.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("20261030121500.gkg.csv", make_gkg_line("https://example.test/a", V2_LOCATIONS))
    dest = tmp_path / "out" / "x.locations.jsonl.gz"
    assert download_gkg.convert_zip(archive, dest) == 1
    with gzip.open(dest, "rt", encoding="utf-8") as handle:
        assert json.loads(handle.readline())["url"] == "https://example.test/a"


def test_stamps_for_day() -> None:
    import datetime as dt

    assert len(download_gkg.stamps_for_day(dt.date(2026, 10, 30), 1)) == 96
    assert download_gkg.stamps_for_day(dt.date(2026, 10, 30), 4)[1] == "20261030010000"


def test_gdelt_matrix_and_query() -> None:
    jobs = harvest_gdelt.load_matrix()
    assert len(jobs) == 16 * 5
    fire_en = next(j for j in jobs if j["topic"] == "spill" and j["language"] == "english")
    assert fire_en["query"] == '("oil spill" OR "chemical spill" OR "toxic leak") sourcelang:english'


def gdelt_article(url: str) -> dict[str, Any]:
    return {
        "url": url,
        "title": "Fire at plant",
        "seendate": "20261030T101500Z",
        "domain": "x.test",
        "language": "English",
        "sourcecountry": "United States",
    }


def test_gdelt_run_jobs_dedupes_and_merges_topics() -> None:
    articles = [gdelt_article("https://x.test/1"), gdelt_article("https://x.test/2"), {"url": "javascript:x"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps({"articles": articles}))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = [
        {"topic": "fire", "language": "english", "query": "q"},
        {"topic": "explosion", "language": "english", "query": "q"},
    ]
    limiter = common.RateLimiter(0.0)
    stats = harvest_gdelt.run_jobs(client, jobs, {"timespan": "1h"}, limiter)
    assert stats["written"] == 2 and stats["failed"] == 0
    again = harvest_gdelt.run_jobs(client, jobs, {"timespan": "1h"}, limiter)
    assert again["written"] == 0
    path = common.raw_dir("news", "gdelt") / "2026-10-30.jsonl"
    rows = list(common.iter_jsonl(path))
    assert len(rows) == 2 and rows[0]["topics"] == ["fire", "explosion"]


def test_gdelt_non_json_body_counts_as_failure() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="Your query was too short")))
    stats = harvest_gdelt.run_jobs(client, [{"topic": "t", "language": "l", "query": "q"}], {}, common.RateLimiter(0.0))
    assert stats["failed"] == 1 and stats["written"] == 0


@pytest.mark.parametrize(
    "address,public",
    [
        ("8.8.8.8", True),
        ("10.0.0.5", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("192.168.1.1", False),
        ("::1", False),
        ("fd00::1", False),
    ],
)
def test_is_public_address(address: str, public: bool) -> None:
    assert fat.is_public_address(address) is public


def test_check_url_blocks_private_resolution() -> None:
    with pytest.raises(fat.BlockedError):
        fat.check_url("http://internal.test/x", resolver=lambda host: ["10.1.2.3"])
    with pytest.raises(fat.BlockedError):
        fat.check_url("file:///etc/passwd")
    with pytest.raises(fat.BlockedError):
        fat.check_url("http://127.0.0.1/")
    fat.check_url("https://news.test/a", resolver=lambda host: ["93.184.216.34"])


class StubDetector(fat.LanguageDetector):
    def detect(self, text: str) -> tuple[str | None, float | None]:
        return "en", 0.99


HTML = """<html><head><title>Fire at the Dayton plant</title></head><body><article>
<p>A fire broke out on Tuesday at a manufacturing plant in Dayton, Ohio, and crews worked through the night to
contain it. Officials said no injuries were reported and the cause is under investigation by the fire marshal.</p>
<p>The company said production would resume once inspectors had cleared the building for re-entry, a process
that could take several days according to local authorities who are coordinating the response.</p></article>
</body></html>"""


def make_fetcher(handler: Any) -> fat.ArticleFetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": "TestAgent/1.0"})
    return fat.ArticleFetcher(
        client,
        domain_interval=0.0,
        resolver=lambda host: ["93.184.216.34"],
        detector=StubDetector(),
        sleep=lambda _: None,
    )


def test_fetch_extracts_text_and_stores_only_snippet() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html; charset=utf-8"})

    article = make_fetcher(handler).fetch("https://news.test/story")
    assert article.status == "ok" and article.language == "en"
    record = article.to_record()
    assert len(record["snippet"]) <= 300 and "text" not in record
    assert record["text_chars"] > 300


def test_fetch_honors_robots_and_ssrf_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    assert make_fetcher(handler).fetch("https://news.test/private/x").status == "robots_disallowed"

    def redirecting(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    result = make_fetcher(redirecting).fetch("https://news.test/go")
    assert result.status.startswith("blocked")


def test_fetch_caps_response_size() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"x" * (fat.MAX_BYTES + 10), headers={"content-type": "text/html"})

    assert make_fetcher(handler).fetch("https://news.test/big").status.startswith("blocked")


def test_fetch_treats_unreachable_robots_as_disallowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert make_fetcher(handler).fetch("https://news.test/a").status == "robots_disallowed"


def test_real_language_detector_identifies_languages() -> None:
    detector = fat.LanguageDetector()
    assert (
        detector.detect("A fire broke out on Tuesday at a manufacturing plant in Dayton and crews responded.")[0]
        == "en"
    )
    assert (
        detector.detect("Un incendio se declaró el martes en una planta de fabricación y los bomberos acudieron.")[0]
        == "es"
    )
    assert detector.detect("Brand")[0] is None  # too short to classify
