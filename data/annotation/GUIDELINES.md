# Annotation guidelines for the gold evaluation sets

These rules define what annotators mark in the mention gold set and the event gold set.
They are versioned with the data. When a rule changes, record the change in the
revision table at the end and re-review affected items.

## General rules

- Work only from the text shown. Do not search for the article or use outside knowledge
  about the event, except to identify which place a name refers to.
- Never annotate or record anything about a named private individual. If the subject of
  a crime or incident report is a named private person, tick `subject_is_named_private_person`
  and do not label the event location.
- Mark an item `needs_second_review` instead of guessing.
- Two annotators label a shared 20 percent of items. Disagreements are resolved in a
  review pass and both original labels are kept for the agreement report.

## Mention gold set

Target: 400 sentences, at least 100 ambiguous, 50 with facilities, 60 non-English.

### What counts as a place mention

Mark a span when it names a specific geographic location: country, region, county,
city, town, village, district, river, lake, island, mountain, or a named facility.
Mark the shortest span that is the name, without articles or qualifiers:
"Rotterdam", not "the port of Rotterdam" (unless "Port of Rotterdam" is the name).
A qualifier that is part of the disambiguating name stays inside the span when it is written
as a unit: "Springfield, Illinois" is two mentions only if the comma separates two
independent names; mark "Springfield" (target: the Illinois city) and "Illinois" separately.

Do not mark:
- Demonyms and adjectives ("Turkish", "Parisian").
- Place names used as organizations or metonyms for people ("Washington said").
  Mark them `NOT_A_PLACE` when the surface form is a place name but the use is not
  geographic. This gives the system negative examples.
- Names of people that share a place name ("Paris Hilton").
- Generic nouns ("the city", "the port").

### Place versus facility

- `PLACE`: administrative or natural geographic units.
- `FACILITY`: a named built site with a function: port, container terminal, airport,
  railway station, power station, refinery, factory or plant, dam, bridge, tunnel,
  border crossing, military base, hospital, stadium. "Port of Rotterdam", "Heathrow",
  "Fukushima Daiichi" are facilities. "Rotterdam" alone is a place.
- A facility named after a city without a facility word ("Dayton plant" is a facility
  mention only when the span includes the facility type: "Dayton plant"; if only "Dayton"
  is the span it is a place).

### Target identifiers

Enter, per mention, one of:
- A Wikidata item id such as `Q90`. Preferred whenever an item exists.
- A GeoNames id written `gn:2988507` when there is no Wikidata item.
- `NIL` when the place exists but neither source has it, or the name is too vague to
  resolve from the text (for example "the town" is not marked, but "Springfield" with no
  context at all is `NIL`).

Check the item type. A mention of a river must not be linked to a town of the same name.

### Ambiguity flag

Set `ambiguous` when at least two well-known places share the name (Springfield, Paris,
Georgetown, Santiago, Valencia, Birmingham, Alexandria, Victoria, Washington, Portland,
San Jose, London). Otherwise `unambiguous`. The flag describes the name, not how hard the
sentence is.

### Languages

Annotate in the language of the text. Record the target id, not a translation.

## Event gold set

Target: 300 articles, with event type, severity, true event location, and nearness to
the synthetic assets shown.

### Event location

The event location is where the reported disruption physically occurred, at the finest
level the article supports. It is not the dateline, the outlet city, the place where an
official spoke, or the home of a company that owns a site.

Choose the level:
- `facility`: a named site ("fire at the Dayton plant").
- `city`: a city, town, or village.
- `admin2`, `admin1`: a county or state level event (a storm warning for a county).
- `country`: only the country is stated.
- `unknown`: no location is given.

If the article reports several locations (a storm crossing three states), record the
location named first in the headline or lead and set the level to the broadest unit that
contains the reported impact. If two events are reported, label the one in the headline.

### Event type and severity

Use the type list in the label configuration. Use `none` when the item is not a
disruption (opinion, history, sports result). Severity:
1. Minor: brief, local, no stated damage or closure.
2. Moderate: localized damage or disruption, closures of hours.
3. Major: significant damage, injuries, or closures of a day or more.
4. Severe: widespread damage, multiple fatalities, or loss of a major facility or route.
Judge from reported facts only.

### Nearness to a synthetic asset

For each synthetic asset in the task, answer yes when the asset lies within the area
affected by the event as described, or within the uncertainty of the location level
(25 km for city events, 2 km for facility events, the whole unit for admin events).
Otherwise no. Assets are illustrative and represent no real company.

## Revision table

| Version | Date | Change |
|---|---|---|
| 1 | 2026-10-30 | Initial guidelines |
