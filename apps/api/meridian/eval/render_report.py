"""Render docs/eval/report.md and public/metrics.json from the last evaluation run."""

from __future__ import annotations

import json
import time
from typing import Any

from meridian.config import REPO_ROOT
from meridian.eval.run import DOCS_DIR, EVAL_DIR, TARGETS

NAMES = {
    "S1": "S1 largest-population GeoNames match",
    "S2": "S2 GeoNames with country and region context",
    "S4": "S4 BELA alone",
    "S5": "S5 BELA + type filter + routing + gazetteer fallback + context re-ranking",
    "S6": "S6 S5 + local model adjudication",
}


def pct(value: float | None) -> str:
    return "n/a" if value is None or value != value else f"{value * 100:.1f}%"


def km(value: float | None) -> str:
    return "n/a" if value is None or value != value else (f"{value:,.1f}" if value < 10 else f"{value:,.0f}")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def system_row(name: str, m: dict[str, float]) -> list[Any]:
    detection = (
        "n/a (gold spans given)"
        if name in ("S1", "S2")
        else f"{pct(m['detection_precision'])} / {pct(m['detection_recall'])} / {pct(m['detection_f1'])}"
    )
    return [
        NAMES[name],
        detection,
        pct(m["acc_25km"]),
        pct(m["acc_161km"]),
        pct(m["acc_25km_matched"]),
        pct(m["acc_161km_matched"]),
        km(m["median_error_km"]),
        km(m["mean_error_km"]),
        m["auc_all"],
    ]


def targets(result: dict[str, Any]) -> list[list[Any]]:
    t = result["table"]
    rows: list[list[Any]] = []
    best_baseline = max((t[s]["ambiguous"]["acc_161km"] for s in ("S1", "S2") if s in t), default=None)
    hybrid_key = "S6" if "S6" in t else "S5"
    if best_baseline is not None:
        gain = t[hybrid_key]["ambiguous"]["acc_161km"] - best_baseline
        rows.append(
            [
                "Hybrid beats the best gazetteer baseline by at least 5 points of accuracy within 161 km on the ambiguous subset",
                f"{gain * 100:+.1f} points ({hybrid_key} {pct(t[hybrid_key]['ambiguous']['acc_161km'])} vs {pct(best_baseline)})",
                "met" if gain >= TARGETS["hybrid_gain_acc161_ambiguous"] else "not met",
            ]
        )
    rows.append(
        [
            "Median error at most 25 km on the event gold set for facility and city events",
            "event gold set not built",
            "not evaluated",
        ]
    )
    throughput = result.get("throughput", {}).get("passages_per_second")
    rows.append(
        [
            "BELA stage at least 20 passages per second on the target GPU",
            f"{throughput} passages per second" if throughput else "not measured",
            "met"
            if throughput and throughput >= TARGETS["bela_passages_per_second"]
            else ("not met" if throughput else "not evaluated"),
        ]
    )
    c6 = result["counters"].get("S6", {})
    if c6.get("resolved"):
        share = c6.get("llm", 0) / c6["resolved"]
        rows.append(
            [
                "At most 25 percent of mentions needing LLM adjudication",
                f"{share * 100:.1f}% of resolved mentions",
                "met" if share <= TARGETS["max_llm_share"] else "not met",
            ]
        )
    return rows


def render(result: dict[str, Any]) -> str:
    t = result["table"]
    out = [
        "# Place linking evaluation",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `make eval`. BELA checkpoint `{result['checkpoint']}`, configuration `geo_config_v1`.",
        "",
        "## Data and protocol",
        "",
        "- Corpora: the public geoparsing corpora LGL, TR-News, GeoWebNews, GeoVirus, and a seeded sample of WikToR, converted by "
        "`data/scripts/download_eupeg.py`. Documents are split 50/50 by hash into **dev** (used to train the re-ranker and to fit "
        f"calibration) and **test** (all figures below). Test split: {result['documents']['test']} documents, {result['test_gold']:,} gold toponyms; "
        f"dev split: {result['documents']['dev']} documents.",
        "- Each gold toponym has a character span and coordinates. Systems that detect their own spans (S4 to S6) are matched to gold spans "
        "by overlap (intersection over union of at least 0.4). **A gold toponym with no matching prediction counts as wrong** in the "
        "first accuracy columns; the 'matched only' columns exclude them.",
        "- S1 and S2 are given the gold spans, so they measure disambiguation only; detection is not applicable to them.",
        "- The ambiguous subset is the gold toponyms whose name matches at least two places in the knowledge base "
        f"({result['ambiguous_gold']:,} of {result['test_gold']:,}).",
        "- S3 (GDELT's own extracted locations) has no gold to score against on the public corpora, which predate GDELT's article "
        "coverage. It is compared with the hybrid system as an agreement study on current news (last section).",
        "- Not evaluated: the hand-labeled mention and event gold sets (no annotation has been done), BLINK re-ranking (S7, see "
        "ADR-002), event type and severity F1 (phase 4), NIL handling, and the Mewsli-X sanity check.",
        "",
        "## Results on the test split",
        "",
        table(
            [
                "System",
                "Detection P / R / F1",
                "Acc 25 km",
                "Acc 161 km",
                "Acc 25 km (matched)",
                "Acc 161 km (matched)",
                "Median km",
                "Mean km",
                "Error-curve AUC (lower is better)",
            ],
            [system_row(n, t[n]["all"]) for n in NAMES if n in t],
        ),
        "",
        "### Ambiguous names only",
        "",
        table(
            [
                "System",
                "Detection P / R / F1",
                "Acc 25 km",
                "Acc 161 km",
                "Acc 25 km (matched)",
                "Acc 161 km (matched)",
                "Median km",
                "Mean km",
                "AUC",
            ],
            [system_row(n, t[n]["ambiguous"]) for n in NAMES if n in t],
        ),
        "",
        "### By corpus (accuracy within 161 km, all gold toponyms)",
        "",
    ]
    corpora = sorted({k.removeprefix("corpus_") for s in t.values() for k in s if k.startswith("corpus_")})
    out += [
        table(
            ["System", *corpora],
            [
                [NAMES[n].split(" ")[0], *[pct(t[n].get(f"corpus_{c}", {}).get("acc_161km")) for c in corpora]]
                for n in NAMES
                if n in t
            ],
        ),
        "",
    ]
    s5, s6 = result["counters"].get("S5", {}), result["counters"].get("S6", {})
    if s5.get("mentions"):
        routes = {k.removeprefix("route_"): v for k, v in s5.items() if k.startswith("route_")}
        out += [
            "## Routing (S5, test split)",
            "",
            table(
                ["Route", "Mentions", "Share"],
                [[r, f"{n:,}", pct(n / s5["mentions"])] for r, n in sorted(routes.items())],
            ),
            "",
        ]
    if s6.get("mentions"):
        out += [
            "## Local model use (S6, test split)",
            "",
            f"Mentions adjudicated by the local model: {s6.get('llm', 0):,} of {s6['resolved']:,} resolved mentions "
            f"({pct(s6.get('llm', 0) / s6['resolved'])}). Run time {s6.get('seconds', 0)} s.",
            "",
        ]
    th = result.get("throughput", {})
    if th:
        out += [
            "## Throughput and latency (BELA stage on the Apple GPU)",
            "",
            table(
                ["Measure", "Value"],
                [
                    ["Documents", f"{th['documents']:.0f}"],
                    ["Passages", f"{th['passages']:.0f}"],
                    ["Passages per second", th["passages_per_second"]],
                    ["Document request p50 / p95", f"{th['p50_document_seconds']} s / {th['p95_document_seconds']} s"],
                ],
            ),
            "",
        ]
    out += [
        "## Calibration of the confidence by route",
        "",
        "Isotonic regression fitted on the dev split; the target is a prediction within 25 km. Figures are on the test split.",
        "",
    ]
    for route, c in result["calibration"].items():
        if "skipped" in c:
            out += [f"- `{route}`: not calibrated ({c['skipped']})."]
        else:
            out += [
                f"- `{route}`: expected calibration error {c['test_ece_before']} before and {c['test_ece_after']} after "
                f"(dev {c['dev_n']:,} predictions, test {c['test_n']:,})."
            ]
    run = DOCS_DIR / "throughput.json"
    if run.exists():
        tp = json.loads(run.read_text(encoding="utf-8"))
        out += [
            "",
            "## Throughput test on real articles",
            "",
            f"{tp['articles']:,} news articles ({', '.join(tp['languages'])}) through the complete pipeline "
            f"(chunking, BELA, routing, fallback, re-ranking, event location; no local model) with {tp['workers']} client workers.",
            "",
            table(
                ["Measure", "Value"],
                [
                    ["Articles", f"{tp['articles']:,}"],
                    ["Failures", tp["failures"]],
                    ["Total time", f"{tp['seconds'] / 60:.1f} minutes"],
                    ["Articles per second", tp["articles_per_second"]],
                    ["Mentions per article", tp["mentions_per_article"]],
                    ["Latency p50 / p95", f"{tp['p50_seconds']} s / {tp['p95_seconds']} s"],
                    ["Passed", "yes" if tp["passed"] else "no"],
                ],
            ),
        ]
    agree = DOCS_DIR / "gkg_agreement.json"
    if agree.exists():
        g = json.loads(agree.read_text(encoding="utf-8"))["summary"]
        out += [
            "",
            "## Agreement with GDELT's own locations (system S3)",
            "",
            f"Sample: {g['articles_fetched']} current English news articles ({g['articles_sampled']} sampled, "
            f"{g['fetch_failures']} could not be fetched, robots.txt honored) with the locations GDELT's GKG extracted for them. "
            "There is no gold, so this measures agreement between two automatic systems; where they differ either may be right.",
            "",
            table(
                ["Measure", "Value"],
                [
                    [
                        "GDELT city and state locations that the hybrid also found (within 25 km, 161 km for states)",
                        f"{pct(g['gkg_locations_covered_by_ours'])} of {g['gkg_locations']:,}",
                    ],
                    [
                        "Hybrid city and region places that GDELT also lists",
                        f"{pct(g['our_places_confirmed_by_gkg'])} of {g['our_places']:,}",
                    ],
                    [
                        "Hybrid event location within range of GDELT's first location",
                        f"{pct(g['event_location_matches_first_gkg_location'])} of {g['event_locations']:,} articles",
                    ],
                ],
            ),
        ]
    out += ["", "## Targets", "", table(["Target", "Result", "Status"], targets(result)), ""]
    return "\n".join(out)


def public_metrics(result: dict[str, Any], places_indexed: int) -> dict[str, Any]:
    t = result["table"]
    best = "S6" if "S6" in t else "S5"
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "docs/eval/report.md",
        "evaluation": "public geoparsing corpora (LGL, TR-News, GeoWebNews, GeoVirus, WikToR sample), test split",
        "places_indexed": places_indexed,
        "median_error_km": t[best]["all"]["median_error_km"],
        "acc_161km": t[best]["all"]["acc_161km"],
        "acc_161km_ambiguous": t[best]["ambiguous"]["acc_161km"],
        "acc_161km_best_gazetteer_baseline_ambiguous": max(
            t[s]["ambiguous"]["acc_161km"] for s in ("S1", "S2") if s in t
        ),
        "system": NAMES[best],
    }


def main() -> int:
    from meridian.db import connect

    result = json.loads((EVAL_DIR / "result.json").read_text(encoding="utf-8"))
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "report.md").write_text(render(result), encoding="utf-8")
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM places")
        row = cur.fetchone()
    public = REPO_ROOT / "public"
    public.mkdir(exist_ok=True)
    (public / "metrics.json").write_text(
        json.dumps(public_metrics(result, int(row[0]) if row else 0), indent=1) + "\n", encoding="utf-8"
    )
    print("wrote docs/eval/report.md and public/metrics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
