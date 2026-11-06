# ADR-013: Application frontend

Status: accepted

## Context

Phase 9 adds the product pages to the Next.js project built in phase 8. The pages must work against the live API,
respect roles, stay usable by keyboard, and give every chart and map a non-visual alternative.

## Decisions

1. **One project, client rendered application.** Pages under `/app` fetch from the same-origin `/api` proxy after a
   session check. Static generation gives no benefit for per-user data, and a single origin keeps cookies and the
   strict content security policy simple.
2. **Small in-house data layer.** A `useApi` hook with stale-answer protection and a fetch wrapper that refreshes the
   token once on a 401. No client cache library is added: pages are few, lists are paged on the server, and reloads
   are explicit.
3. **ECharts behind `ChartCard`.** One wrapper gives every chart a table view, PNG and CSV export, and consistent
   states. Modular imports keep the bundle limited to the chart types used.
4. **Map layers by data size.** Assets (up to 5,000) are a clustered circle layer rendered on the GPU. Incidents
   (hundreds) are symbols whose shape and size encode level, so color is never the only signal.
5. **Roles in one table.** `nav.ts` holds who may open each route; the sidebar, the palette, and the route guard all
   read it. The server remains the authority; the guard only avoids showing pages that would answer 403.
6. **Transparency data from the API, not the client.** The incident page shows every candidate place with its BELA,
   gazetteer, context, re-ranking and model scores. That needed `location_candidates` on the event detail and a read
   grant on `mention_candidates` (migration 0010). Mentions are derived from public text and hold no tenant data.
7. **Untrusted text stays text.** Evidence snippets are rendered as text with highlighted place names; generated
   briefings are shown in a sandboxed frame.

## Consequences

- Per-customer revenue history, invoice aging, and monthly overage need API endpoints that do not exist yet; the page
  says so instead of inventing numbers.
- Removing `'unsafe-inline'` from `script-src` is still open (nonces need dynamic rendering).
- A client cache can be added later if pages begin to share requests.
