# Metric definitions

Every revenue metric is defined once, in SQL (`apps/api/migrations/sql/0008_metrics.sql`), and the API only reads those views. All
figures come from synthetic demo data and are labeled as such. Revenue figures are in USD.

## Conventions

- **Month end.** The last calendar day of a month. The last month reported is the latest month that has ended (`last_complete_month()`).
- **Active.** A subscription is active at a month end when `start_date <= month end` and (`end_date` is null or `end_date >= month end`).
  `end_date` is the last day of service. A plan or price change ends one row and starts the next on the following day.
- **Monthly equivalent.** The recurring fee of a subscription per month. For an annual subscription, `price` is the annual amount and the
  monthly equivalent is `price / 12`.

## Revenue

| Metric | Definition | Where |
|---|---|---|
| MRR | Sum of monthly equivalent fees of active subscriptions at month end. Overage is not included. | `tenant_mrr_monthly`, `mrr_monthly` |
| ARR | MRR times 12. | `mrr_monthly.arr` |
| Overage | Overage lines of invoices, by the month of the invoice period. Reported apart from MRR. | `overage_monthly` |
| Movements | Per tenant and month, the change in MRR against the previous month end, classified as **new** (no MRR before; returning customers count as new), **expansion** (more), **contraction** (less, still above zero), or **churn** (falls to zero). | `mrr_movements` |
| Net new MRR | New + expansion − contraction − churn. It equals the change in MRR from the previous month, which is tested for every month. | `mrr_monthly.net_new_mrr` |
| Customers | Tenants with MRR above zero at month end. | `mrr_monthly.customers` |

## Retention

| Metric | Definition |
|---|---|
| Net revenue retention (NRR), trailing 12 months | MRR now of the customers that were active twelve months ago, divided by their MRR then. New customers are excluded; expansion, contraction, and churn count. |
| Gross revenue retention (GRR), trailing 12 months | Sum over those customers of `min(MRR now, MRR then)`, divided by their MRR then. Never above 100 percent and never above NRR. |
| Cohort retention | Customers are grouped by the month of their first subscription. For each month since signup: customers still active, and MRR, as a share of the cohort's starting values. |
| Logo churn | Customers lost in a month divided by customers at the previous month end. |

## Unit economics

| Metric | Definition |
|---|---|
| ARPA | MRR divided by active customers. |
| Quick ratio | (New + expansion MRR) divided by (contraction + churned MRR). Empty when nothing was lost. |
| CAC | Marketing spend of the month divided by new customers of the month. Months with few new customers are noisy, so a trailing three month CAC (spend and new customers summed over three months) is also given. |
| Payback (months) | Trailing three month CAC divided by (ARPA × gross margin). |
| LTV | ARPA × gross margin divided by monthly logo churn (trailing three months). Empty when no customer was lost in those months. |
| Gross margin | A fixed assumption of 80 percent (`gross_margin()`), shown to the user as an assumption, not a measurement. |

## Forecast

`GET /platform/revenue/forecast` fits exponential smoothing (statsmodels `ETSModel`, additive error, damped additive trend) to up to 36
months of monthly MRR and projects up to 12 months (default 6) with an 80 percent prediction interval. It needs at least 18 months of
history. It is labeled **Estimate** in the response and must be labeled the same way wherever it is shown. It is a statistical
extrapolation, not a plan.

## Slices and filters

`plan`, `region`, `industry`, and `channel` filters apply to MRR, customers, movements, and stacked series. They use the attributes of a
tenant in the month in question. Two consequences:

- Movements reconcile to the change in MRR for any filter on a fixed attribute (region, industry, channel). With a **plan** filter an
  upgrade appears as expansion in the new plan while that plan's MRR jumps by the full amount, so the plan-filtered movements do not add up.
- Retention and unit economics are company wide. With a filter they are returned empty, with a note.

## Operational analytics

| Metric | Definition |
|---|---|
| Alerts by level | Alerts created per period by level (`ops_stats_daily`, or the alert tables for days without a statistics row). |
| Acknowledgement rate | Acknowledged alerts divided by alerts. |
| Time to acknowledge | Average over days of the daily median minutes from alert creation to first acknowledgement, weighted by acknowledged alerts. |
| Location confirmation rate | Alerts acknowledged without a wrong-location correction, divided by acknowledged alerts that were confirmed or corrected. A proxy for reviewer feedback: an analyst who acknowledges an alert accepts its location. |
| False alert rate | Dismissed alerts divided by closed (dismissed or resolved) alerts, weighted by incidents ingested. |
| Detection delay | Median minutes from the time an event occurred to the time it was first seen. |
| Detection delay versus hazard feeds | For events seen both in a hazard feed (USGS, NWS, FIRMS) and in the news: the median minutes by which the first news report followed the first feed record. |
| Routing breakdown | Share of place mentions by route: accept, adjudicate, fallback, unresolved. |
| Incident volumes | Events by first seen date, by type, subtype, region (of the resolved place's country), or country. |
| Exposure by region | Exposures by the region of the asset's country and level, with counts of exposures, assets, and tenants. No asset names or positions. |

Daily statistics are written by the nightly job (`python -m meridian.api.worker`, after 02:00 UTC) for tenants with live activity. Synthetic
tenants are filled by the demo data loader, and the job never overwrites them.

## Refresh and caching

The materialized views are refreshed nightly and on demand (`POST /platform/revenue/refresh`, platform administrators, or `make metrics-refresh`).
Responses are cached in the API process for 60 seconds per scope (tenant or platform) and parameters; a refresh clears the cache and makes older
entries unreachable. Responses carry an `ETag` and `Cache-Control: private`, so clients can revalidate cheaply. Every analytics endpoint takes `from`,
`to`, `granularity` (day, week, month; quarter for revenue), `compare` (none, previous_period, previous_year), the filters that apply to it, and
`format=csv` for an export in which text cells that a spreadsheet could read as formulas are neutralised.
