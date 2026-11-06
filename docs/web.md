# Web application (phase 8)

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

`apps/web` is the Next.js project. Phase 8 delivers the foundation and the marketing site; the product application (`/app`) comes in phase 9.
Decisions are in `docs/adr/ADR-012-frontend-foundation.md`.

## Run

```
make web-install            # npm ci
make api-up                 # API on 127.0.0.1:8090 (separate terminal)
make web-dev                # http://localhost:3000, /api proxied to MS_API_URL
make web-build web-start    # production build and server
```

Settings: `MS_API_URL` (default `http://127.0.0.1:8090`), `NEXT_PUBLIC_SITE_URL` (canonical URLs, sitemap, Open Graph).

## Structure

| Path | Content |
|---|---|
| `src/app` | Routes: home, platform, solutions, industries, pricing, security, developers, methodology, resources, company, contact, legal, login, forgot and reset password, newsletter confirmation, `/app` landing, sitemap, robots, Open Graph images (`/og/<key>.png`) |
| `src/components/ui` | Button, Input, Textarea, Select, Checkbox, Field, Card, Badge and SeverityBadge, Accordion (FAQ), Tabs, Dialog and drawer, Skeleton, EmptyState, Breadcrumbs, Stepper, Timeline, Toast, Reveal |
| `src/components/site` | Utility bar, header with keyboard navigable mega menus, footer with newsletter, cookie notice, page blocks |
| `src/components/art` | Logo, illustrations, product renderings, world map, severity markers |
| `src/components/map-view.tsx` | Shared MapLibre map: clustering, shape and color by level, uncertainty circles, accessible table alternative |
| `src/content` | Typed site content, evaluation tables, six MDX articles |
| `messages` | Interface strings in English, Spanish, French and German |
| `scripts` | Image pipeline, map worker copy, axe report, Lighthouse run, screenshots |
| `e2e`, `tests` | Playwright and Vitest |

## Data the site reads

- `src/lib/metrics.json`: copy of `public/metrics.json` (a test fails if they differ).
- `GET /api/v1/public/stats`: places indexed, incidents in the last 30 days, source records by kind. Counts only.
- `make web-geo`: regenerates country outlines and recent hazard points from the database.

## Quality gates

```
make web-check     # eslint, tsc, prettier, vitest
make web-e2e       # Playwright against a running site and API (needs a test user, see below)
make web-axe       # axe-core on every route at 375 and 1440 px, writes reports/axe.json
make web-quality   # Lighthouse desktop on six pages, gates: accessibility >= 95, CLS <= 0.1, home performance >= 90
make web-screens   # full page screenshots at 375, 768, 1024, 1440, 1920 px, and a horizontal overflow check
```

The sign-in tests need an analyst account in a tenant with slug `web-e2e`
(`python -m meridian.api.cli create-tenant --name "Web E2E"` then `create-user --role analyst --tenant web-e2e` with
`MS_NEW_PASSWORD` set, email `e2e.analyst@example.org`). The MFA test creates its own administrator.

Results of the last run are in `apps/web/reports/axe.json` and `apps/web/reports/lighthouse-home.json`.

| Check | Result |
|---|---|
| axe-core, WCAG 2.2 AA tags, 31 routes at 375 and 1440 px | 0 violations |
| Lighthouse desktop, home | performance 100, accessibility 100, best practices 96, SEO 100, CLS 0.003 |
| Lighthouse desktop, other pages | performance 96 to 100 before a layout fix on the contact page; 100 after; accessibility 100 |
| Horizontal overflow at 375, 768, 1024, 1440, 1920 px | none on the eight reviewed pages |
| Playwright | 10 site tests (content, skip link, mega menu keyboard, language, demo request, newsletter, sign-in, reset request, console errors, security headers) and one MFA enrollment test, all passing |

The login page scores 66 for SEO on purpose: it is marked `noindex`.

## Honest gaps

- Photographs and application screenshots are not used (see ADR-012). Product views are labeled illustrative renderings.
- Page copy is English only.
- `script-src` still allows `'unsafe-inline'`. Removing it needs per-request nonces, which Next.js supports only for dynamically rendered pages; phase 10 reviewed it and kept it (see `docs/security.md`): nonces would make the statically generated marketing pages dynamic, and the map and chart libraries write inline styles.
- Visual review was done on screenshots of eight pages at five widths by the author, not by a designer.
- Lighthouse was run against the production build on the development machine, not over a network.
- Newsletter confirmation mail goes through the configured mailer; with no SMTP server the send is logged as failed and the subscription stays pending.

## Application (phase 9)

The product lives under `/app` in the same Next.js project. It is client rendered behind a session check; every page
reads the live API through the same-origin `/api` proxy.

| Area | Routes |
|---|---|
| Monitor | `/app` overview, `/app/map`, `/app/incidents`, `/app/incidents/[id]`, `/app/alerts` (with Rules tab) |
| Portfolio | `/app/assets` (upload wizard, bulk edit, saved views), `/app/assets/[id]`, `/app/zones` |
| Insight | `/app/briefings`, `/app/reports`, `/app/analytics`, `/app/sources` |
| Organisation | `/app/billing`, `/app/admin` (users, API keys, webhooks, audit log, risk and security) |
| Platform | `/app/platform/revenue`, `/app/platform/analytics` |
| Account | `/app/settings` (profile, authenticator setup with QR code, sessions, notifications) |

Shell: sidebar by role, search palette (Ctrl or Cmd + K) over pages, assets, incidents and places, live alert bell fed
by the server-sent event stream, light and dark theme, route guards by role, silent token refresh with one retry,
30 minute idle timeout with a warning, an error boundary, and shortcuts (`?` lists them; `g` then a letter navigates;
`j`, `k`, `a`, `d` on the alert queue).

Charts use Apache ECharts through one `ChartCard` wrapper: every chart has a table view, PNG and CSV export (CSV cells
that start with a formula character are quoted), and loading, empty and error states. Dashboards share date presets,
granularity, and an "as of" time. Revenue and billing carry a "Demo data" label.

The map is MapLibre with clustered GPU circle layers for assets, symbol layers for incidents (shape and size change
with level), uncertainty circles, a density layer, distance rings around a selected asset, time slider with replay,
polygon and circle drawing, and view and filters kept in the address. Every map page has a table alternative.

### Running the application tests

```
make api-up                      # API on 127.0.0.1:8090
make web-build && make web-start # site on localhost:3000
make web-e2e                     # all Playwright tests, including the application suite
```

The application suite signs in as five local accounts in tenant `web-e2e` (`mgr`, `ta`, `viewer` at
`@example.org`) and the platform roles (`pa`, `fin`); create them with `meridian.api.cli create-user` and the shared
`MS_NEW_PASSWORD`. Accounts that need an authenticator are enrolled on first use and the secrets are kept in
`.local/dev_mfa.json` (ignored by git). `make web-seed` adds illustrative assets near current incidents so alerts exist.
The sign-in rate limit is per address, so restart the API if a run is blocked by it.

| Check | Result |
|---|---|
| Playwright, application | 10 workflow tests: upload wizard, draw a watch zone, open an incident, acknowledge an alert by keyboard, export a report, map filters in the address, role restrictions, API key shown once with audit chain check, revenue dashboard, platform role menu |
| axe-core on 15 application pages | 0 violations |
| Full suite | 67 passing |

### Gaps in the application

- Hex density is a heat layer, not H3 hexagons.
- The source filter on the map separates hazard feeds from other reports by event type, because list items carry no
  source kind.
- Invoice PDFs are not generated by the server; the billing page offers print to PDF.
- The revenue page shows billing totals only. The API has no cross-customer invoice list, per-customer history, or
  monthly overage series, so aging buckets, the customer drill-down history and a monthly revenue mix are not shown.
- Analytics: language mix is not exposed by the API; incident volume is computed in the browser from the 200 most
  recent incidents of the period.
- Zone rule testing is an approximation (bounding box and type and severity of the last 30 days), not a replay.
- Security settings (required authenticator for administrators, session lifetime) are fixed platform policy and shown
  read only. Risk configuration history lists only changes made during the current page session.
- The map clusters carry no count labels because the basemap has no glyph source.
- Performance with 5,000 markers was not measured against a frame rate target in this phase; it is scheduled with the
  load tests.
- Screenshots were reviewed by the author at 1440 and 375 px for 24 pages, not by a designer.


## Cross-browser and accessibility audit (phase 10)

The full end-to-end suite (67 tests: 10 site, 1 MFA, 31 marketing accessibility, 10 application workflow, 15 application
accessibility) was run on 2026-11-04 against the production build, one browser at a time (`npm run e2e:cross`, or
`--project=<name>`):

| Browser | Engine | Result |
|---|---|---|
| Chromium (Playwright build) | Blink | 67 passed |
| Google Chrome (installed, current) | Blink | 67 passed |
| Firefox (Playwright build) | Gecko | 67 passed |
| WebKit (Playwright build) | the engine of Safari | 67 passed |
| Microsoft Edge | Blink | not run: Edge is not installed on the test machine. It shares the engine of the Chrome run; the `msedge` project is configured and runs where Edge is installed. |

Safari itself was not run; WebKit is the same engine but not the same product. Differences found and handled:

- Firefox reported a content security policy violation from the form validation library, which probes for `Function()` support.
  The library is now configured not to probe (`jitless`).
- WebKit does not move focus to links with the Tab key unless the user turns that on, so the skip-link test focuses the link directly
  in that browser. The link itself is reachable in every browser by its position in the page.
- The demo request and newsletter endpoints allow five requests per hour per address; running four browsers from one address in a
  row exhausts that, so restart the API (or wait) between browsers when repeating the suite.

Accessibility: axe-core runs on 31 marketing pages and 15 application pages in the Chromium run with no violations at WCAG 2.2 AA
tags; the map pages provide a list and table alternative. The automated checks do not replace a manual audit with a screen reader;
none was done in this phase.
