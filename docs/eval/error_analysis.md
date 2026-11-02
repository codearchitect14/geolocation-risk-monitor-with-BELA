# Error analysis (hybrid system, test split)

| Outcome | Gold toponyms | Share |
|---|---:|---:|
| resolved_within_25km | 3,795 | 58.7% |
| span_not_detected | 975 | 15.1% |
| resolved_wrong | 712 | 11.0% |
| span_detected_unresolved | 526 | 8.1% |
| resolved_within_161km | 458 | 7.1% |

## resolved_wrong

| Surface | Corpus | Error km | Detail |
|---|---|---:|---|
| Mansfield | lgl | 7,370 |  |
| Mansfield | lgl | 329 |  |
| Mansfield | lgl | 329 |  |
| Mansfield | lgl | 7,370 |  |
| Mansfield | lgl | 329 |  |
| Alexandria | lgl | 1,640 |  |
| Brandon | lgl | 275 |  |
| New Haven | lgl | 1,011 |  |
| Louisville | lgl | 1,679 |  |
| Alexandria | lgl | 969 |  |
| Alexandria | lgl | 969 |  |
| Arlington | lgl | 1,924 |  |
| Arlington | lgl | 1,924 |  |
| Arlington | lgl | 1,924 |  |
| Washington | lgl | 3,600 |  |

## span_not_detected

| Surface | Corpus | Error km | Detail |
|---|---|---:|---|
| MANSFIELD | lgl |  |  |
| Mansfield | lgl |  |  |
| Shreveport | lgl |  |  |
| Mansfield | lgl |  |  |
| Shreveport | lgl |  |  |
| America | lgl |  |  |
| Ky. | lgl |  |  |
| S.D. | lgl |  |  |
| Ariz. | lgl |  |  |
| Palestinian | lgl |  |  |
| Gaza | lgl |  |  |
| Palestinian | lgl |  |  |
| Israel | lgl |  |  |
| Syrians | lgl |  |  |
| Syrians | lgl |  |  |

## span_detected_unresolved

| Surface | Corpus | Error km | Detail |
|---|---|---:|---|
| Douglas County | lgl |  | unresolved: best candidate below the resolution threshold |
| Lake Vermont | lgl |  | unresolved: local model: The name 'Lake Vermont' in the context refers to a location near Alexandria, mentioned in relation to County Road 35. Among the candidates, none exactly match 'Lake Vermont' as a named lake or feature |
| Freeborn Lake | lgl |  | unresolved: non-geographic entity Q20709753 outscores places |
| Des Plaines | lgl |  | unresolved: best candidate below the resolution threshold |
| Mansfield | lgl |  | unresolved: best candidate below the resolution threshold |
| Mansfield | lgl |  | unresolved: best candidate below the resolution threshold |
| Arlington | lgl |  | unresolved: best candidate below the resolution threshold |
| Arlington | lgl |  | unresolved: best candidate below the resolution threshold |
| Arlington | lgl |  | unresolved: best candidate below the resolution threshold |
| Gratis | lgl |  | unresolved: local model: The name 'Gratis' appears in the context of a rural community in Walton County, which is in the U.S. state of Georgia. Among the candidates, none exactly match 'Gratis' as a place name. However, 'Free |
| Athens | lgl |  | fallback: entity linking score below the adjudication threshold |
| Athens | lgl |  | unresolved: best candidate below the resolution threshold |
| Knox Park | lgl |  | unresolved: best candidate below the resolution threshold |
| Madison County | lgl |  | unresolved: best candidate below the resolution threshold |
| Madison County | lgl |  | unresolved: best candidate below the resolution threshold |

## resolved_within_161km

| Surface | Corpus | Error km | Detail |
|---|---|---:|---|
| Middle East | lgl | 149 |  |
| Oconee | lgl | 108 |  |
| Kanawha River | lgl | 77 |  |
| Kanawha River | lgl | 70 |  |
| Anthony Creek | lgl | 111 |  |
| Cranberry | lgl | 157 |  |
| Hopkins Park | lgl | 135 |  |
| Britian | lgl | 119 |  |
| Lindsay | lgl | 138 |  |
| Lindsay | lgl | 138 |  |
| Abkhazia | lgl | 27 |  |
| Abkhazia | lgl | 27 |  |
| Abkhaz | lgl | 27 |  |
| Abkhaz | lgl | 27 |  |
| Avnevi | lgl | 43 |  |
