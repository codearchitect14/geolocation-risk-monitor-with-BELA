"""Child process: HTML on stdin, PDF on stdout. Only data: URIs are loaded; every other resource is refused."""

from __future__ import annotations

import sys


def main() -> int:
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher

    html = sys.stdin.buffer.read().decode("utf-8")
    fetcher = URLFetcher(allowed_protocols=["data"], allow_redirects=False)
    sys.stdout.buffer.write(HTML(string=html, url_fetcher=fetcher).write_pdf())
    return 0


if __name__ == "__main__":
    sys.exit(main())
