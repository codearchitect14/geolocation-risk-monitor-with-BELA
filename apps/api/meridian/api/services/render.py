"""Rendering of PDF and map images in separate processes.

WeasyPrint and the headless browser load native libraries and parse markup, so they run as short lived child processes
with a time limit and no network use: the PDF renderer refuses every external resource, and the map page is a self contained
SVG. A failure returns None and the caller keeps the HTML report.
"""

from __future__ import annotations

import logging
import os
import subprocess  # noqa: S404 - fixed argument lists only
import sys
from pathlib import Path

log = logging.getLogger("meridian.render")
TIMEOUT_SECONDS = 90
MAX_OUTPUT = 40 * 1024 * 1024


def _environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}}
    if "MS_PDF_LIB_PATH" in os.environ:
        env["DYLD_FALLBACK_LIBRARY_PATH"] = os.environ["MS_PDF_LIB_PATH"]
    elif sys.platform == "darwin" and Path("/opt/homebrew/lib").is_dir():
        env["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib"
    # The child needs the application package on its path when it is started from another directory.
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    return env


def _run(module: str, data: bytes) -> bytes | None:
    try:
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-m", module],
            input=data,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            env=_environment(),
            cwd=str(Path(__file__).resolve().parents[3]),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("%s failed: %s", module, type(exc).__name__)
        return None
    if done.returncode != 0 or not done.stdout or len(done.stdout) > MAX_OUTPUT:
        log.warning("%s exited with %s", module, done.returncode)
        return None
    return done.stdout


def html_to_pdf(html: str) -> bytes | None:
    pdf = _run("meridian.api.services.pdf_child", html.encode("utf-8"))
    return pdf if pdf and pdf.startswith(b"%PDF") else None


def svg_to_png(svg: str) -> bytes | None:
    png = _run("meridian.api.services.map_child", svg.encode("utf-8"))
    return png if png and png.startswith(b"\x89PNG") else None
