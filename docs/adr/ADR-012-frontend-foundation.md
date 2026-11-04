# ADR-012: Frontend foundation and marketing site

- Status: accepted
- Date: 2026-11-03

## Context

Phase 8 delivers the Next.js application shell, design system, marketing website and the authentication pages. The product
application (phase 9) reuses the same project, tokens and components.

## Decisions

- **One Next.js project in `apps/web`** (App Router, TypeScript strict, Tailwind CSS 4 with tokens declared in `@theme`). Marketing pages are
  statically generated. Pages that read live figures (the home page) use incremental regeneration every five minutes and fall back to the
  repository figures when the API is unreachable.
- **Single origin.** The browser calls `/api/*` on the web origin, and `next.config.ts` rewrites it to the API. Cookies are first party, CORS stays
  off, and the CSRF double submit header is read from the `ms_csrf` cookie by `src/lib/api.ts`.
- **Strict Content Security Policy** (own origin for scripts, styles, fonts, images, connections, workers; no framing). Next.js inlines small
  bootstrap scripts, so `script-src` keeps `'unsafe-inline'`. Phase 9 replaces it with per-request nonces once pages are rendered per request.
  The map worker is copied to `public/maplibre` at build time so no `blob:` script origin is needed.
- **Own components on Radix primitives** (accordion, tabs, dialog, navigation menu), styled to the tokens. Only components the site uses were
  built; the data table, combobox, date picker, command palette, file dropzone and chart components belong to phase 9, where they have a use.
- **Interface strings in four languages, page copy in English.** `next-intl` runs in a client provider and the choice is kept in local storage, so
  every page stays static. The cost is that translated chrome appears after load. Translating page copy needs routed locales and is a later decision.
- **Imagery is in-house.** Stock photography could not be retrieved from this environment (both sites require an interactive client or a key),
  so industry and article images are vector scenes rendered by `scripts/build-images.mjs` through the same pipeline that will process
  photographs placed in `apps/web/src-images/` (AVIF and WebP, four widths, explicit dimensions). Product images are labeled illustrative
  renderings, because the application they depict is built in phase 9; real screenshots replace them then.
- **Basemap without tiles.** Country outlines exported from the gazetteer (Natural Earth) are the basemap, so no tile server or third party
  origin is contacted. `data/scripts/export_web_geo.py` writes the outlines and recent hazard points.
- **Evidence in code.** Figures on the site come from `metrics.json` (copied into the project, with a test that the copy matches the repository
  file), from `src/content/eval.ts` (copied from `docs/eval/report.md`, tested against `metrics.json`), or from the public statistics
  endpoint. A test fails if an article leaves the 900 to 1,400 word range, or if an em dash or an assistant or vendor name appears.

## Backend additions

Migration 0009 adds `demo_requests.role`, `industry` and `consent_at`, and a `newsletter_subscribers` table. New endpoints:
`POST /newsletter/subscribe` (double opt-in; the same answer for new, pending and confirmed addresses), `POST /newsletter/confirm`,
`GET /public/stats` (counts only, cached five minutes). The demo request now requires consent.

## Consequences

- No real photography or screenshots yet. The pipeline and credits file are ready for them.
- The language selector does not translate page bodies.
- `script-src 'unsafe-inline'` remains until phase 9.
