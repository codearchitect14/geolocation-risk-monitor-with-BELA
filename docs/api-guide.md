# API guide

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

The reference is `docs/openapi.json` (92 paths), also served at `/api/docs` outside production. This guide shows how to authenticate
and the calls most integrations need. Base URL in the examples: `http://127.0.0.1:8090/api/v1` (the demonstration).

## Authentication

**API keys** are for programs. An administrator creates one in the application (Administration, API keys), chooses scopes
(`read`, `alerts`, `assets:write`, `reports`) and an expiry, and sees the secret once. Send it as `Authorization: Bearer msk_...`
or `X-API-Key: msk_...`. Keys are limited to 120 requests per minute by default (`429` with `Retry-After` beyond that).

**Sessions** are for people: `POST /auth/login` sets httpOnly cookies and a CSRF cookie. Send the CSRF value back in the
`X-CSRF-Token` header on every request that is not a GET. Administrators complete a TOTP step after the password.

Errors use the problem format: `{"type": ..., "title": ..., "status": ..., "detail": ..., "code": ...}`.

## Incidents

```bash
export MS=http://127.0.0.1:8090/api/v1
export KEY=msk_xxxxxxxx_yyyyyyyyyyyyyyyyyyyyyyyy

# Incidents in a bounding box (min_lon,min_lat,max_lon,max_lat), severity 2 or higher, newest first
curl -s -H "Authorization: Bearer $KEY" "$MS/events?bbox=-125,24,-66,50&min_severity=2&limit=50"

# One incident with its sources, timeline, location candidates, and the disclaimer
curl -s -H "Authorization: Bearer $KEY" "$MS/events/$EVENT_ID"
```

```python
import httpx

client = httpx.Client(base_url="http://127.0.0.1:8090/api/v1", headers={"Authorization": f"Bearer {KEY}"})
page = client.get("/events", params={"min_severity": 2, "limit": 50}).json()
for event in page["items"]:
    print(event["severity"], event["type"], event["title"])
while page["next_cursor"]:  # keyset paging: pass the cursor back
    page = client.get("/events", params={"min_severity": 2, "limit": 50, "cursor": page["next_cursor"]}).json()
```

```javascript
const MS = "http://127.0.0.1:8090/api/v1";
const headers = { Authorization: `Bearer ${process.env.KEY}` };
const res = await fetch(`${MS}/events?min_severity=2&limit=50`, { headers });
const { items, next_cursor } = await res.json();
```

Lists return `{"items": [...], "next_cursor": "..." | null}`. `limit` is at most 200. `format=geojson` returns a FeatureCollection.

## Alerts

```bash
# New alerts, most urgent first (scope: alerts)
curl -s -H "Authorization: Bearer $KEY" "$MS/alerts?status=new&limit=50"
# Acknowledge one (people sign in with a session; the lifecycle is enforced on the server)
curl -s -X PATCH -H "Content-Type: application/json" -b cookies.txt -H "X-CSRF-Token: $CSRF" \
  -d '{"status": "acknowledged"}' "$MS/alerts/$ALERT_ID"
```

Statuses move new, acknowledged, escalated, resolved, or dismissed; a dismissal needs a reason.

## Assets

```bash
# Upload a CSV (columns: name, lat, lon, city, country, criticality, type, external_id, tags). Template: GET /uploads/template
curl -s -H "Authorization: Bearer $KEY" -F "file=@assets.csv;type=text/csv" "$MS/uploads"
# List, search, export
curl -s -H "Authorization: Bearer $KEY" "$MS/assets?q=warehouse&limit=100"
curl -s -H "Authorization: Bearer $KEY" "$MS/assets-export" -o assets.csv
```

Uploads take up to 5,000 rows and 5 MB per file; coordinates are validated and rows without a usable position are rejected with a
reason per row. An `Idempotency-Key` header makes a retried upload safe.

```python
with open("assets.csv", "rb") as handle:
    result = client.post("/uploads", files={"file": ("assets.csv", handle, "text/csv")}).json()
print(result["rows_accepted"], result["rows_rejected"])
```

## Locating text

`POST /locate` links the places in a piece of text and chooses one event location, with every candidate and score. It is limited
to 30 requests a minute per user or key and 20,000 characters per call.

```bash
curl -s -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"title": "Fire at chemical plant", "text": "A fire broke out in Springfield, Illinois.", "lang": "en"}' "$MS/locate"
```

## Webhooks

Create a webhook in Administration (HTTPS endpoints with public addresses only). Each delivery carries
`X-Meridian-Signature: t=<unix time>,v1=<hex>` where `v1` is HMAC-SHA256 of `<t>.<body>` with the signing secret, and
`X-Meridian-Delivery: <id>`. Reject deliveries whose timestamp is more than five minutes old. Failed deliveries retry at 1 minute,
5 minutes, 30 minutes, 2 hours, and 12 hours.

```python
import hashlib, hmac, time

def valid(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    if abs(time.time() - int(parts["t"])) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{parts['t']}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

Webhook and email payloads contain no asset coordinates unless the tenant has opted in.

## Live updates

`GET /stream/alerts` and `GET /stream/events` are server-sent event streams scoped to the caller's tenant (at most 20 open streams
per tenant). Each message is an `update` event; fetch the list again to read what changed.

## Limits worth knowing

| Limit | Value |
|---|---|
| Requests per address | 300 per minute |
| Requests per user | 600 per minute |
| Requests per API key | 120 per minute |
| Body size | 1 MB (uploads 5 MB) |
| Page size | 200 |
