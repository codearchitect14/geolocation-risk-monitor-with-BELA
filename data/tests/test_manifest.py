from pathlib import Path

import common
import verify_manifest

README = Path(__file__).resolve().parents[1] / "README.md"


def test_repository_manifest_is_well_formed() -> None:
    assert verify_manifest.check_structure(common.load_manifest()) == []


def test_every_manifest_script_exists() -> None:
    for source in common.load_manifest()["sources"]:
        if source.get("script"):
            script = source["script"]
            path = common.SCRIPTS_DIR.parents[1] / script if "/" in script else common.SCRIPTS_DIR / script
            assert path.exists(), source["id"]


def test_readme_licensing_register_lists_every_source() -> None:
    text = README.read_text(encoding="utf-8")
    for source in common.load_manifest()["sources"]:
        assert f"`{source['id']}`" in text, f"{source['id']} missing from the licensing register"


def test_verify_detects_changed_file(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.txt").write_text("hello", encoding="utf-8")
    entry = {"path": "raw/a.txt", "size": 5, "sha256": common.sha256_file(tmp_path / "raw" / "a.txt")}
    manifest = {"sources": [{"id": "s", "kind": "static", "files": [entry]}]}
    problems, status = verify_manifest.verify_files(manifest, tmp_path)
    assert problems == [] and status["s"] == "1/1 verified"
    (tmp_path / "raw" / "a.txt").write_text("HELLO", encoding="utf-8")
    problems, _ = verify_manifest.verify_files(manifest, tmp_path)
    assert problems and "checksum mismatch" in problems[0]
