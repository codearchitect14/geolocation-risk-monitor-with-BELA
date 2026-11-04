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
- `script-src` keeps `'unsafe-inline'` until phase 9.
- Visual review was done on screenshots of eight pages at five widths by the author, not by a designer.
- Lighthouse was run against the production build on the development machine, not over a network.
- Newsletter confirmation mail goes through the configured mailer; with no SMTP server the send is logged as failed and the subscription stays pending.
