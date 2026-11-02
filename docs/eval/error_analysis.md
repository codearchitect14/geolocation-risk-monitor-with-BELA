# Error analysis (hybrid system, test split)

| Outcome | Gold toponyms | Share |
|---|---:|---:|
| resolved_within_25km | 3,451 | 53.4% |
| span_not_detected | 1,151 | 17.8% |
| span_detected_unresolved | 919 | 14.2% |
| resolved_wrong | 531 | 8.2% |
| resolved_within_161km | 414 | 6.4% |

## span_detected_unresolved

| Surface | Corpus | Error km | Detail |
|---|---|---:|---|
| Avoyelles | lgl |  | unresolved: best candidate below the resolution threshold |
| Cottonport | lgl |  | unresolved: best candidate below the resolution threshold |
| Cottonport | lgl |  | unresolved: best candidate below the resolution threshold |
| Avoyelles Parish | lgl |  | unresolved: best candidate below the resolution threshold |
| Pointe Coupee | lgl |  | unresolved: best candidate below the resolution threshold |
| Shreveport | lgl |  | unresolved: best candidate below the resolution threshold |
| Shreveport | lgl |  | unresolved: best candidate below the resolution threshold |
| Lake Vermont | lgl |  | unresolved: local model: The name 'Lake Vermont' in the context refers to a location near Alexandria, and the mention of 'County Road 35' and 'north of Alexandria' suggests a U.S. location. Among the candidates, none exactly名 |
| Freeborn Lake | lgl |  | unresolved: non-geographic entity Q20709753 outscores places |
| Middle East | lgl |  | unresolved: best candidate below the resolution threshold |
| Des Plaines | lgl |  | unresolved: best candidate below the resolution threshold |
| Mansfield | lgl |  | unresolved: best candidate below the resolution threshold |
| Mansfield | lgl |  | unresolved: best candidate below the resolution threshold |
| Arlington | lgl |  | unresolved: best candidate below the resolution threshold |
| Arlington | lgl |  | unresolved: best candidate below the resolution threshold |

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
| Alexandria | lgl |  |  |
| Palestinian | lgl |  |  |
| Gaza | lgl |  |  |
| Palestinian | lgl |  |  |
| Israel | lgl |  |  |
| Syrians | lgl |  |  |

## resolved_wrong

| Surface | Corpus | Error km | Detail |
|---|---|---:|---|
| Brandon | lgl | 275 |  |
| Alexandria | lgl | 757 |  |
| New Haven | lgl | 1,011 |  |
| Alexandria | lgl | 757 |  |
| Louisville | lgl | 1,679 |  |
| Alexandria | lgl | 969 |  |
| Mansfield | lgl | 7,536 |  |
| MANSFIELD | lgl | 7,536 |  |
| Mansfield | lgl | 7,536 |  |
| Washington | lgl | 3,600 |  |
| Athens | lgl | 918 |  |
| Madison County | lgl | 1,241 |  |
| Athens | lgl | 10,016 |  |
| Decatur | lgl | 605 |  |
| Loudon Co. | lgl | 698 |  |

## resolved_within_161km

| Surface | Corpus | Error km | Detail |
|---|---|---:|---|
| Oconee | lgl | 108 |  |
| East Hampton | lgl | 73 |  |
| Chesterton | lgl | 97 |  |
| Kanawha River | lgl | 77 |  |
| Hopkins Park | lgl | 135 |  |
| Britian | lgl | 119 |  |
| Lindsay | lgl | 138 |  |
| Abkhazia | lgl | 27 |  |
| Abkhaz | lgl | 42 |  |
| Abkhaz | lgl | 42 |  |
| Avnevi | lgl | 43 |  |
| Caucasus | lgl | 136 |  |
| Calif. | lgl | 56 |  |
| Afghanistan | lgl | 93 |  |
| Afghanistan | lgl | 93 |  |
