# Licensing register

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

This page summarizes the licenses of what the project uses. It is an inventory for engineers, not legal advice; confirm terms
before redistributing data or shipping the software to others.

## This repository

The repository has **no license file yet**. Until the owner chooses one, all rights are reserved by default. Choose a license
before inviting outside use or contributions; the dependency review below lists the components that constrain the choice
(`Unidecode`, GPL).

## Data and models

The register of data sources, required attribution, redistribution terms, and where each is credited in the product is in
`data/README.md` (section "Licensing register"). The sources are Wikidata, GeoNames, Natural Earth, GDELT, article text
(snippets only), multilingual CC-News (testing only), USGS, NWS, NASA FIRMS, ReliefWeb, the EUPEG and Mewsli-X evaluation corpora,
and the models BELA (MIT), the XLM-R tokenizer (MIT), Qwen3-4B-Instruct-2507 (Apache-2.0), and bge-m3 (MIT). GDACS is excluded
until its reuse terms are confirmed.

What the repository itself commits from external sources:

| File | Source | Terms |
|---|---|---|
| `data/seed/replays/usgs_earthquakes.jsonl` (160 records) | USGS earthquake feed | Public domain; USGS is credited on the sources page and the methodology page |
| `data/gold/*` | the project's own annotation | own work |
| `apps/web/src/lib/metrics.json`, `public/metrics.json` | the project's own evaluation | own work, on public corpora that are not redistributed |

Hazard feed operators state that automated products should not be used for decisions without confirmation; the product repeats
that wherever records are shown.

## Software dependencies

Inventory taken on 2026-11-04 from the installed environments (183 Python distributions; 294 production npm packages).

| Ecosystem | Licenses present | Needs attention |
|---|---|---|
| Python | MIT (about 75), BSD (about 45), Apache-2.0 (about 35), ISC, PSF, Unlicense, and a few others | see below |
| npm (production) | MIT 242, ISC 14, Apache-2.0 13, BSD 12, 0BSD 4, MPL-2.0 3, OFL-1.1 2, LGPL-3.0 1, CC-BY-4.0 1 | see below |

Components with copyleft or notice obligations:

| Component | License | Where used | Note |
|---|---|---|---|
| Unidecode 1.4.0 | GPL-2.0-or-later | transliteration of place names in `meridian/geo/names.py` | Strong copyleft. Fine for internal use and the evaluation; **resolve before distributing the software or offering it as a service**: replace it (for example with `anyascii`, ISC) and re-run the place knowledge base build and the evaluation, since normalized names feed matching |
| psycopg, psycopg-binary, psycopg-pool | LGPL-3.0 | database access | Used as a library through its public interface; keep it replaceable (do not vendor modified copies) |
| pyphen (through WeasyPrint) | GPL-2.0+ / LGPL-2.1+ / MPL-1.1 (choose) | hyphenation in PDF reports | Use under MPL or LGPL |
| tld | MPL-1.1 / GPL-2.0 / LGPL-2.1 (choose) | URL parsing (trafilatura chain, data scripts) | Use under MPL or LGPL; not in the API runtime image |
| certifi, orjson, bidict, pathspec, tqdm | MPL-2.0 | various | File level copyleft; unmodified use needs no action |
| `@img/sharp-libvips` | LGPL-3.0 | image build script only | Build tool; not shipped in the web image |
| lightningcss, next-mdx-remote | MPL-2.0 | web build and content | File level copyleft; unmodified use needs no action |
| caniuse-lite | CC-BY-4.0 | browser support data in the build | Attribution to the Browserslist contributors in this register |
| Inter, JetBrains Mono (`@fontsource-variable`) | OFL-1.1 | self-hosted fonts | Fonts may be embedded and served; the license text ships in the packages |
| zope.interface, zope.event | ZPL-2.1 | transitive | Permissive |

The product embeds no third-party map tiles, photographs, or logos (`apps/web/public/images/CREDITS.md`).

Regenerate the Python list with `pip-licenses --from=mixed` in the project environment, and the npm list by reading the
`license` field of each production package in `apps/web/node_modules`.
