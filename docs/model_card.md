# Model card: place linking and event geolocation engine

Configuration version: `geo_config_v1` (status: initial, see "Calibration status"). Evaluation: `docs/eval/report.md`.
This product gives situational awareness, not official warnings. Signals are derived from public news and public
data feeds; verify with local authorities and follow their guidance.

## What the engine does

Given a news article it (1) finds place mentions, (2) links each to a place with coordinates and an uncertainty
radius, and (3) chooses one event location with a confidence. Mentions that cannot be resolved stay unresolved and
are never placed on a map. An event whose best location is a country is flagged country level and is not matched
against site assets.

| Step | Component |
|---|---|
| Mention detection and entity linking | BELA (XLM-R large context encoder; MIT licensed release by Meta), checkpoint `model_wiki.ckpt`, 16.5 million entity index |
| Type filter | Candidates must be rows of the place knowledge base (Wikidata and GeoNames merge, phase 2) |
| Routing | Accept, adjudicate, or fall back by link score and margin (thresholds in `geo_config_v1.yaml`) |
| Gazetteer fallback | Capitalized strings that match a place name or alias but were missed by BELA |
| Context re-ranking | Gradient boosting over 21 features (link score, name match, population prior, countries in the article, outlet country, qualifiers such as "Springfield, Illinois", agreement with other places, distance to the cluster of places) |
| Adjudication | Qwen3-4B-Instruct-2507 (Apache-2.0) in llama.cpp, JSON-schema constrained, only when the two best candidates stay close |
| Event location | Rules: headline and lead position, preposition cues, specificity, repetition, consistency with other places |

The project builds on the open-source BELA release and is not affiliated with its authors.

## Intended use

Linking places named in public news text to coordinates so reports can be matched to a customer's sites and routes,
with every decision shown with its evidence (candidates, scores, route, model versions). Output is an input to an
exposure score and never the final alert decision on its own.

Not intended for: tracking or profiling individuals (the event classifier drops reports whose subject is a named
private person), evacuation or safety-of-life guidance, address-level geocoding, or any use of customer asset
locations for training.

## Data

- Place knowledge base: Wikidata (CC0), GeoNames (CC BY), Natural Earth (public domain); see `data/README.md`. The
  Wikidata part of the current build is partial (first six million dump lines), which limits what BELA can link.
- BELA checkpoints were trained by the authors on Wikipedia based data. No customer data and no data from this
  project was used for training any model.
- The re-ranker is trained on the **dev half** of public geoparsing corpora (LGL, TR-News, GeoWebNews, GeoVirus, a
  sample of WikToR). It has not seen the test half.

## Evaluation

See `docs/eval/report.md` for the figures, protocol, and what was not evaluated. In brief: accuracy within 25 and 161 km,
median and mean distance error, and detection precision and recall on the test half of the public corpora, for two
gazetteer baselines, BELA alone, the hybrid, and the hybrid with the local model.

Not yet evaluated, because the data does not exist: the hand-labeled mention and event gold sets; event type and
severity F1; the share of false alerts; behavior on languages beyond the few present in the public corpora.

## Calibration status

Confidence by route is calibrated with isotonic regression on the dev half and checked on the test half. The event
location confidence is a heuristic (score share and position evidence), **not calibrated**, because there is no event
gold set. Thresholds are initial values; they become `frozen` when calibrated on the gold sets.

## Limitations and failure modes

- **Small places.** BELA only knows entities with a Wikipedia based vector. Villages, plants, and most facilities
  reach the pipeline through the gazetteer fallback, which has weaker evidence (no entity linking score).
- **Common names.** "Springfield", "Georgetown", "Birmingham": without a qualifier, a country in the article, or other
  places nearby, the most populous namesake wins. Expect errors on short items with a single place name.
- **Outlet country bias.** The outlet country is a feature. Reports from local outlets favor the local namesake,
  which is usually right and wrong for foreign news about a namesake abroad.
- **Scripts without letter case** (Chinese, Japanese, Arabic, Hindi, Thai): the capitalized-span fallback does not
  apply, so only BELA's detections are used.
- **Transliteration variants** and **historic names** resolve only if they exist as aliases.
- **Non-place use of place names** ("Washington said"): handled by the type filter when BELA is confident that the
  entity is not a place; otherwise the mention may be linked.
- **Event location.** The selector can pick the dateline or an official's seat of government rather than the place of
  the event, especially for national news. Country level results are labeled as such.
- **The local model** can be wrong while returning valid JSON. Its adjudication is shown with its reason; it is
  never used alone to raise an alert.
- Article text is untrusted. Prompts wrap it in delimiters and instruct the model to treat it as data; a test
  confirms an embedded instruction did not change a label. This is mitigation, not a guarantee.

## Versions stored with each decision

Configuration version, re-ranker version, local model prompt version, and BELA checkpoint name are stored with
every decision so results can be reproduced and compared.
