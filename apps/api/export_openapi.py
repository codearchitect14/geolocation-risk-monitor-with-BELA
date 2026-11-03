"""Write the OpenAPI document to docs/openapi.json."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MS_ENV", "test")
os.environ.setdefault("MS_SECRET_KEY", "x" * 43 + "=")  # never used: the document is built without handling requests
os.environ.setdefault("MS_JWT_PRIVATE_KEY", "unused")

from meridian.api.main import create_app  # noqa: E402

target = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
target.write_text(json.dumps(create_app().openapi(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {target}")
