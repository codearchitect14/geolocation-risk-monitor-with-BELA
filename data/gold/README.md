# Gold evaluation sets

Hand-labeled sets used by the evaluation harness. Files are exported from Label Studio
and converted with `data/scripts/export_label_studio.py`; check them with
`make validate-gold`.

| File | Content |
|---|---|
| `mentions.jsonl` | One sentence per line: text, language, split, and its labeled mentions |
| `events.jsonl` | One article per line: title, snippet, link, event type, severity, event location, asset nearness |

Mention record:

```json
{"id": "m0001", "text": "...", "lang": "en", "split": "dev",
 "mentions": [{"start": 10, "end": 21, "surface": "Springfield", "label": "PLACE",
               "target": "Q28515", "ambiguous": true}]}
```

`label` is `PLACE`, `FACILITY`, or `NOT_A_PLACE`. `target` is a Wikidata id (`Q...`), a GeoNames
id (`gn:123`), or `NIL`. `NOT_A_PLACE` mentions have target `NIL`.

Event record:

```json
{"id": "e0001", "url": "https://...", "title": "...", "snippet": "...", "lang": "en",
 "split": "test", "event_type": "industrial_accident", "severity": 3,
 "location": {"name": "...", "target": "Q...", "lat": 0.0, "lon": 0.0, "level": "facility"},
 "assets": [{"asset_id": "A1", "lat": 0.0, "lon": 0.0, "near": true}],
 "private_person_subject": false}
```

Snippets are at most 300 characters. Do not store full article text here.
Annotation rules are in `data/annotation/GUIDELINES.md`.
