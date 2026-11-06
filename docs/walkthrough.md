# Product walkthrough

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

A ten minute tour for a demonstration, using the data that `make demo` creates. Everything shown is synthetic or illustrative:
the portfolio, the revenue history, and the incidents, which are a recorded public earthquake feed re-timed to the present.
Sign in with the accounts printed when the demonstration was set up. Capture screenshots of each step with `make screenshots`
(set `DEMO_EMAIL` and `DEMO_PASSWORD` to include the product pages; files go to `apps/web/reports/screenshots`).

Before you start: `make demo` (first time), then `make replay` in a second terminal when you reach step 5.

## 1. The promise (1 minute): marketing site

Open `/`. Say: the platform turns public reports into a short list of sites that need attention, and shows its work. Scroll to the
three steps (find, locate, score), then `/methodology` and point at the evaluation table: the figures are measured on public
corpora, the hardest cases (ambiguous names) are reported separately, and the page lists what was not evaluated.

## 2. Sign in (30 seconds)

`/login` shows the demonstration box. Sign in as the **viewer** (read only). Mention that administrators use an authenticator app.

## 3. Overview (1 minute): `/app`

The cards answer "what needs me now": open alerts by level, incidents near assets, and the trend. Point at the disclaimer in the
footer: signals support attention, they are not official warnings.

## 4. Map (2 minutes): `/app/map`

Markers differ by shape and size as well as color (level 1 to 4). Assets with a red outline are exposed. Toggle **Density**, then
**Show as list**: the map has a table alternative for keyboard and screen reader users. Use the **Replay** slider to move back in
time. The filters are in the address bar, so a view can be shared.

## 5. Incidents (2 minutes): `/app/incidents`

Run `make replay` now. New incidents appear on the map and the notification bell updates. Open an incident:

- **Evidence and sources**: each report with its link and a snippet of at most 300 characters.
- **Location transparency**: for news, the candidate places with their scores and the route the engine took; for a feed record,
  the feed's own coordinates. The uncertainty radius is drawn on the map.
- **Timeline**: first seen, merged reports, status changes.
- **Reduced confidence** badge: appears when a processing component was down and a fallback was used.

## 6. Alerts (2 minutes): `/app/alerts`

Each alert links an incident to an asset with the distance and the score components. Open one and show the score breakdown
(proximity, severity, source reliability, recency, criticality). Sign in as the **manager** to acknowledge with `a`, assign, or
dismiss with a reason; the viewer cannot, which shows the role model. Every step is recorded in the alert history.

## 7. Assets and zones (1 minute): `/app/assets`, `/app/zones`

Upload a CSV through the wizard (template provided; rows without a usable position are rejected with a reason). Draw a watch zone on
the map and show that incidents inside it raise alerts even without a matching asset.

## 8. Reports and briefings (1 minute): `/app/reports`, `/app/briefings`

Create a portfolio report (PDF or CSV). Briefings are written from stored fields only; any number, link, or name in the text is
checked against the evidence before it is shown.

## 9. Operations and trust (1 minute): `/app/sources`, `/app/admin`

The **sources** page shows the state of each feed and of the processing components, and how many incidents were built with a
fallback. In the demonstration the model server and the entity linker show as down because they are not part of it; say so rather than hiding it, since it is the page's purpose. As the **tenant administrator**: users and roles, API keys with scopes, webhooks with signed deliveries, the audit log with
its hash chain verification, and the risk configuration.

## 10. The business view (optional): platform administrator

`/app/platform/revenue` and `/app/platform/analytics` show the synthetic revenue history (recurring revenue, movements, cohorts,
forecast) and platform health. The tenant pages never expose another tenant's data; the platform views contain counts only.

## What not to claim

- The demonstration does not process news: the entity linking model and the language model are not part of it.
- Earthquake magnitudes are automated and can be revised; the feed's operator advises confirming before acting.
- Replayed incidents carry a replay note in their summary.
