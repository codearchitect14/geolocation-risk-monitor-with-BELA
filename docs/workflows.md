# Product workflows (backend)

This describes the behaviour added in phase 6. Endpoints and examples are in `docs/openapi.json`; controls are in `docs/security.md`.
Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

## Asset upload

1. `GET /uploads/template?format=csv|geojson` returns a template.
2. `POST /uploads/stage` (multipart `file`, optional `mapping`) returns the upload with `rows`, `summary`, a `preview` FeatureCollection,
   the detected or given column `mapping`, and the file `headers`. When no name and location columns can be found the answer is 422
   with the headers so the caller can send a mapping such as `{"name": "Site", "city": "Town", "country": "Nation"}`.
3. Row statuses: `ready`, `review` (ambiguous or weak place match; `candidates` lists up to five places), `duplicate` (repeats an
   earlier row of the file), `error` (message says why). `GET /uploads/{id}/rows?status=review` pages through rows.
4. `POST /uploads/{id}/commit` with `{"choices": [{"row": 4, "place_id": 2}], "skip_rows": [7]}` creates the assets. It answers with
   counts and the upload becomes `processed`, `partial`, or `failed`. A second commit is a 409. `POST /uploads/{id}/cancel` discards a
   staged upload.
5. `GET /uploads/{id}/result` is a per row outcome as CSV (formula safe); `GET /assets-export` exports the assets.

Limits: file size and 10,000 rows (`MS_MAX_UPLOAD_ROWS`), vertex count for GeoJSON, UTF-8 text only, coordinates validated, spreadsheet
formulas neutralised on export.

## Asset management

Types are site, route, and region (taken from the geometry). `POST /assets/bulk` changes criticality, status (archive or restore),
tags, group membership, and maintenance windows for up to 1,000 assets in one transaction; one unknown id rejects the whole request.
`PATCH /asset-groups/{id}` renames a group and adds or removes members. `GET /assets` filters by tag, group, minimum criticality,
bounding box, and whether an asset is inside a maintenance window. Alerts are not raised for assets inside a window.

## Watch zones and rules

`POST /zones` takes one of `geometry` (polygon), `circle` (`center` as lon, lat and `radius_km` up to 2,000), or `region_place_id`
(an administrative region with a stored boundary). Zone rules: event types, minimum severity, minimum level, quiet hours (UTC).
Alert rules add asset groups and `escalation.after_minutes` (5 to 10,080).

## Alert lifecycle

Statuses: new, acknowledged, monitoring, escalated, dismissed, resolved.

| From | To |
|---|---|
| new | acknowledged, monitoring, escalated, dismissed, resolved |
| acknowledged | monitoring, escalated, dismissed, resolved |
| monitoring | acknowledged, escalated, dismissed, resolved |
| escalated | acknowledged, monitoring, dismissed, resolved |
| dismissed, resolved | new |

Anything else is a 409 that lists the allowed targets. Dismissal needs a reason. Assignment is limited to active users of the same
tenant. `GET /alerts?mine=true` and `?assignee_id=` filter the queue. Every change is recorded in the alert history.

Notifications: the alert stream (`/stream/alerts`) announces new alerts, status changes (`alert.updated`), and escalations
(`alert.escalated`); webhooks receive new and escalated alerts; email goes to analysts, managers, and administrators for new and
reopened alerts outside quiet hours. `PATCH /auth/me/notifications` turns a user's email off. Escalation runs in the worker
(`python -m meridian.api.worker`).

## Incident detail

`GET /events/{id}` adds `location` (position, uncertainty and an uncertainty circle polygon, the resolved place), `linked_places` (places
resolved in the source articles, the event location first), `timeline` (sources and pipeline updates in time order),
`similar_past_incidents` (same type within 100 km during the previous year) next to `sources`, `updates`, and the tenant's `exposures`
with distance and every score component.

## Briefings

`POST /briefings` builds the evidence and the narrative. Tenants can have them created automatically: set `daily_briefing`,
`weekly_briefing`, and `briefing_email` in `PUT /admin/risk-config`; the worker creates the daily briefing for the previous UTC day
from 06:00 UTC and the weekly one on Mondays, once each. `GET /briefings/{id}?format=html|pdf` downloads the document and
`POST /briefings/{id}/email` sends the PDF to users of the tenant only.

The summary paragraph comes from the local model when its server is running (it uses the GPU through the same server as the event
pipeline) and is checked against the evidence; otherwise the template text is used. `model_version` says which.

## Reports

`POST /reports/incident/{event_id}` and `POST /reports/portfolio` create HTML and PDF (the portfolio also CSV); `GET /reports/{id}?format=`
downloads them and `GET /reports` lists them. An incident report has the summary, location and uncertainty, sources with links and
times, affected assets with score components, a static map, the report id and timestamp, and the disclaimer.

Setup on macOS: `make pdf-setup` (installs pango with Homebrew and the browser used for the map). The renderer looks for the native
libraries in `/opt/homebrew/lib`; set `MS_PDF_LIB_PATH` elsewhere.

## Corrections

`POST /corrections` (any signed in user) records a wrong location, wrong type, or duplicate. Platform administrators see all open
corrections with the event title (`GET /corrections?status=open`) and review each once (`PATCH /corrections/{id}`). Accepted corrections
are noted on the event. Those submitted with consent are appended to `data/annotation/correction_candidates.jsonl` for the next
annotation round.
