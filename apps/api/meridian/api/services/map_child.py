"""Child process: SVG on stdin, PNG on stdout, rendered by a headless browser with the network blocked."""

from __future__ import annotations

import sys


def main() -> int:
    from playwright.sync_api import sync_playwright

    svg = sys.stdin.buffer.read().decode("utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 960, "height": 540}, device_scale_factor=2, java_script_enabled=False)
            page.route("**/*", lambda route: route.abort())
            page.set_content(f'<!doctype html><body style="margin:0">{svg}</body>')
            sys.stdout.buffer.write(page.locator("svg").first.screenshot(type="png"))
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
