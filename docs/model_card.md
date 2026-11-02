# Model card: place linking and event geolocation engine

Configuration version: `geo_config_v1` (status: calibrated on public corpora, see "Calibration status"). Evaluation: `docs/eval/report.md`.
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

Full tables, protocol, and error analysis: `docs/eval/report.md` and `docs/eval/error_analysis.md`. Test split of the public
geoparsing corpora (787 documents, 6,466 gold toponyms, 2,969 of them ambiguous names). Accuracy counts a gold toponym with
no matching prediction as wrong.

| System | Acc within 25 km | Acc within 161 km | Acc 161 km, ambiguous names | Acc 161 km, detected toponyms only |
|---|---:|---:|---:|---:|
| S1 largest-population GeoNames match (gold spans given) | 41.6% | 43.8% | 45.2% | 58.7% |
| S2 GeoNames with country and region context (gold spans given) | 48.1% | 50.5% | 58.6% | 67.6% |
| S4 BELA alone | 25.9% | 29.8% | 26.1% | 85.9% |
| S5 hybrid (no local model) | 58.6% | 65.7% | 69.5% | 85.2% |
| S6 hybrid with local model adjudication | 58.7% | 65.8% | 69.5% | 85.7% |

What the numbers say:

- The hybrid beats the best gazetteer baseline by 10.9 points of accuracy within 161 km on ambiguous names, although the
  baselines were given the gold spans and the hybrid had to find them itself. The target was 5 points.
- BELA alone is accurate when it links a place (85.9% within 161 km) but finds few of the gold toponyms (34.8% recall):
  it ignores place names it does not know and tags organizations and concepts. The gazetteer fallback and the re-ranker
  raise recall to 77%.
- **The local model adds almost nothing measurable** (+0.1 point). It handled 12.9% of resolved mentions (target: at most
  25%). Its value so far is the stored reason shown to analysts; do not claim an accuracy gain from it.
- Calibration (isotonic, fitted on the dev half): expected calibration error on the test half fell from 0.108 to 0.016 for
  adjudicated mentions and from 0.117 to 0.024 for fallback mentions. It barely moved for accepted mentions (0.048 to 0.044).
- Speed: the BELA stage runs at 22 passages per second on the Apple GPU (p95 document latency 0.31 s).

The accuracy figures are conservative in one respect. A prediction counts as a detection only when its span overlaps the gold
span with an intersection over union of at least 0.4, so "Shreveport Police Department" resolved to Shreveport is scored as a
miss for the gold span "Shreveport". The error analysis shows several of the 975 "span not detected" cases are of this kind.
This scoring effect applies equally to S4, S5 and S6.

Outcome of every gold toponym for the hybrid system: 58.7% resolved within 25 km, 7.1% within 161 km, 11.0% resolved
wrongly, 8.1% detected but left unresolved, 15.1% not detected.

Two further checks on real news:

- **Throughput.** 10,000 English, Spanish, and German articles went through the whole pipeline (no local model) with no
  failures at 3.8 articles per second (p95 latency 2.2 s) on the Apple GPU.
- **Agreement with GDELT's own locations** (108 current articles, no gold): the hybrid finds 79% of the city and state
  locations GDELT extracted; only 37% of the places the hybrid reports appear in GDELT's lists (the hybrid reports far more
  places per article). The hybrid's single event location falls within range of GDELT's first location for 35% of articles. This is
  agreement between two automatic systems, not accuracy, and the first GDELT location is not necessarily the event location, but
  the low figure is a reason to treat the event location as unvalidated until the event gold set exists.

Not yet evaluated, because the data does not exist: the hand-labeled mention and event gold sets; event type and severity F1;
the share of false alerts; behavior on languages beyond the few in the public corpora (the corpora are mostly English news).
Detection precision is 41 to 43%: most mentions BELA proposes are not places and are correctly left unresolved, so this figure
mainly reflects the gold sets annotating only some of the places in a text.

## Calibration status

Confidence by route is calibrated with isotonic regression on the dev half and checked on the test half of the public corpora.
The event location confidence is a heuristic (score share and position evidence), **not calibrated**, because there is no event
gold set. Thresholds are set from the public corpora, not from the project's own gold sets, so `geo_config_v1` is marked
`calibrated_on_public_corpora`, not `frozen`.

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
