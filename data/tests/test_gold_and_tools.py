import json
import subprocess
import sys
from pathlib import Path

import common
import export_label_studio as els
import scheduler
import validate_gold as vg

ROOT = Path(__file__).resolve().parents[2]


def mention(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "m1",
        "text": "Fire in Springfield today",
        "lang": "en",
        "split": "dev",
        "mentions": [
            {"start": 8, "end": 19, "surface": "Springfield", "label": "PLACE", "target": "Q28515", "ambiguous": True}
        ],
    }
    row.update(overrides)
    return row


def test_validate_mention_accepts_good_and_flags_bad() -> None:
    assert vg.validate_mention(mention()) == []
    bad = mention(mentions=[{"start": 8, "end": 19, "surface": "Springfiel", "label": "CITY", "target": "Q 1"}])
    problems = vg.validate_mention(bad)
    assert len(problems) == 3


def test_validate_event_rules() -> None:
    good = {
        "title": "t",
        "url": "https://x.test/a",
        "snippet": "s",
        "split": "test",
        "event_type": "natural_hazard",
        "severity": 2,
        "location": {"level": "city", "lat": 1.0, "lon": 2.0},
    }
    assert vg.validate_event(good) == []
    assert "severity must be 1 to 4" in vg.validate_event({**good, "severity": 9})
    private = {**good, "private_person_subject": True}
    assert "private person subject must not carry a location" in vg.validate_event(private)


def test_cohen_kappa() -> None:
    assert vg.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert vg.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0


def test_agreement_on_events(tmp_path: Path) -> None:
    def write(name: str, types: list[str]) -> Path:
        path = tmp_path / name
        path.write_text(
            "".join(
                json.dumps({"id": f"e{i}", "event_type": t, "location": {"level": "city"}}) + "\n"
                for i, t in enumerate(types)
            ),
            encoding="utf-8",
        )
        return path

    result = vg.agreement(
        write("a.jsonl", ["natural_hazard", "none", "other"]), write("b.jsonl", ["natural_hazard", "none", "none"])
    )
    assert result["event_items"] == 3 and result["event_level_agreement"] == 1.0
    assert 0 < result["event_type_kappa"] < 1


def test_export_mention_task() -> None:
    task = {
        "id": 3,
        "data": {"text": "Fire in Springfield today", "lang": "en"},
        "annotations": [
            {
                "result": [
                    {
                        "id": "r1",
                        "type": "labels",
                        "value": {"start": 8, "end": 19, "text": "Springfield", "labels": ["PLACE"]},
                    },
                    {"id": "r1", "type": "textarea", "from_name": "target_id", "value": {"text": ["Q28515"]}},
                    {"id": "r1", "type": "choices", "from_name": "ambiguity", "value": {"choices": ["ambiguous"]}},
                ]
            }
        ],
    }
    row = els.convert_mention_task(task, "m", "dev")
    assert row is not None and vg.validate_mention(row) == []
    assert row["mentions"][0]["target"] == "Q28515" and row["mentions"][0]["ambiguous"] is True
    assert els.convert_mention_task({"id": 4, "data": {"text": "x"}, "annotations": []}, "m", "dev") is None


def test_scheduler_report_flags_stale_job(capsys: object) -> None:
    common.write_status("usgs", True, {})
    assert scheduler.report() == 0
    common.write_status("nws", False, {"error": "boom"})
    assert scheduler.report() == 1


def test_no_em_dash_in_repository() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "infra" / "ci" / "check_no_em_dash.py"), str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
