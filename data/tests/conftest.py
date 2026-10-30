from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Send all raw output to a temporary directory and clear credentials."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("MS_DATA_DIR", str(root))
    for name in ("NWS_USER_AGENT", "MS_CONTACT", "FIRMS_MAP_KEY", "RELIEFWEB_APPNAME"):
        monkeypatch.delenv(name, raising=False)
    return root
