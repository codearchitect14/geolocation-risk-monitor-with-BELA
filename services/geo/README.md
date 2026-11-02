# Geo service

HTTP wrapper around the linking library in `apps/api/meridian/linking` (the library is the product; this is a thin shell).

```
make geo-up        # needs the NEL service (make nel-up) and, optionally, the language model (make llm-up)
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | Config version, re-ranker version, whether the entity linker and the language model are reachable |
| `GET /v1/gazetteer/search?q=&country=&k=` | Place search: exact, alias, and fuzzy name match with a population prior |
| `POST /v1/locate` | Link an article and select its event location. Body: `title`, `text`, `lang`, `outlet_country`, `use_llm` |

`/v1/locate` returns every mention with its route (`accept`, `adjudicate`, `fallback`, `unresolved`), reason, scores,
candidate list, and the chosen place; the event location with level, uncertainty radius, and confidence; the
configuration, re-ranker, and prompt versions; and the standard disclaimer. A country level event location carries
`alertable_against_sites: false`.

Configuration lives in `apps/api/meridian/config/geo_config_v1.yaml`. Released versions are never edited; add a new file.
