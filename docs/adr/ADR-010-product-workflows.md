# ADR-010: Product workflows: guided upload, alert lifecycle, and documents

- Status: accepted
- Date: 2026-11-03

## Context

Phase 6 turns the API into the workflows that analysts and managers use: bringing assets in, watching areas, working alerts, and
producing briefings and reports. The constraints from earlier phases still hold: asset locations are confidential, article text is
untrusted, and a language model never decides an alert on its own.

## Decisions

- **Upload is two steps, and nothing is created until the second.** `POST /uploads/stage` parses and checks every row and returns a
  status per row (ready, review, duplicate, error) with a GeoJSON preview. `POST /uploads/{id}/commit` creates assets from ready
  rows and from review rows with a chosen candidate. The staged rows live in the upload record, so a tab that is closed can be
  reopened. The one step `POST /uploads` from phase 5 remains for scripts that supply coordinates.
- **City plus country goes through the place table, with a person in the loop.** A row is accepted automatically only when a country is
  given, the best match scores at least 0.62, and it leads the runner up by 0.12. Anything else is a review row with up to five
  candidates, and the reviewer's pick must be one of the stored candidates. Such assets are marked `location_source = place` and
  keep the place uncertainty, because a city centroid is not a facility position. Address level geocoding is not offered; the plan
  allows it only with a self-hosted geocoder.
- **Watch zones keep how they were drawn.** A polygon, a circle (center and radius, built in PostGIS on the spheroid), or an
  administrative region (the stored boundary, simplified) are all stored as a polygon; `rules.origin` records the circle or region so
  that an editor can reopen it. Exactly one shape is accepted.
- **The lifecycle is a small state machine.** Closed alerts (dismissed, resolved) can only reopen as new; dismissal needs a reason;
  every change is an `alert_events` row with the actor. A rule can carry `escalation.after_minutes`; the worker moves alerts that
  are still new after that time to escalated, records it as automatic, and notifies in the same ways as a new alert.
- **Notifications by channel.** In-app (the alert stream) always; webhooks by the webhook's minimum level; email only for new or
  reopened alerts, never during the rule's quiet hours, one message per recipient and batch, to analysts, managers, and
  administrators who have not turned it off. Mail and webhooks carry asset names and distances, never coordinates.
- **Briefings are facts first.** The evidence is read from stored rows only (alerts, new and resolved events that expose this tenant,
  groups affected, active weather service alerts that expose assets). The local model, which runs on the GPU through the existing
  server, writes a short summary; the result is accepted only if every number, link, and mid-sentence capitalised name appears in the
  evidence and the disclaimer is present. Otherwise the template text is used. The facts are appended to the summary in either case.
- **Documents are rendered in child processes.** WeasyPrint turns the escaped HTML into a PDF and a headless browser turns an SVG map
  into a PNG. Both run as short lived subprocesses with a time limit; the PDF renderer loads only `data:` URIs, and the browser has
  the network blocked. The map is drawn from stored geometry (country outlines from the place table, the uncertainty circle, and the
  assets); no map tile service is contacted, so asset positions never leave the system. If a renderer is missing, the HTML report is
  still produced and the SVG map is embedded.
- **Corrections need consent to leave the tenant.** Every accepted correction is recorded on the event. Only corrections whose
  submitter ticked the consent box are written to `data/annotation/correction_candidates.jsonl`, without tenant identifiers or free
  text, as candidates for annotators. They are not added to the gold set automatically.

## Consequences

- The API process never loads WeasyPrint or a browser, so a crash or hostile markup in a renderer cannot take it down or reach
  tenant data; the cost is about a second per PDF with a map.
- Reports are generated inside the request (rate limited to 20 per hour per user). A queue is the next step if volumes grow.
- The static map is schematic. It is meant for orientation in a printed document, not navigation.
- Fixed review thresholds can be tuned; they are constants in `services/staging.py`.
