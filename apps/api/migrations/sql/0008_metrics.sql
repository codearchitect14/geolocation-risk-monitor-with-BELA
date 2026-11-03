-- Phase 7: business metric definitions. These views are the single source of truth for revenue metrics (see docs/metrics.md).
-- Definitions
--   month end         the last day of a calendar month; the last month is the latest month that has ended (today included).
--   active            a subscription is active at a month end when start_date <= month end and (end_date is null or end_date >= month end).
--                     end_date is the last day of service.
--   MRR               monthly equivalent recurring fee of active subscriptions at month end; annual prices are divided by 12.
--                     Overage is reported separately (overage_monthly) and is not part of MRR.
--   movements         per tenant and month, the change in MRR against the previous month end: new (first ever or returning),
--                     expansion, contraction, churn (MRR falls to zero). Their sum equals the change in MRR.

ALTER TABLE tenants ADD COLUMN acquisition_channel text;

CREATE FUNCTION gross_margin() RETURNS numeric LANGUAGE sql IMMUTABLE AS $$ SELECT 0.80::numeric $$;

CREATE FUNCTION last_complete_month() RETURNS date LANGUAGE sql STABLE AS $$
    SELECT date_trunc('month', (current_date + 1) - interval '1 month')::date
$$;

CREATE FUNCTION region_of_country(cc text) RETURNS text LANGUAGE sql STABLE AS $$
    SELECT CASE
        WHEN cc IS NULL THEN 'Unknown'
        WHEN cc IN ('US', 'CA') THEN 'North America'
        WHEN cc IN ('AE', 'BH', 'IL', 'IQ', 'IR', 'JO', 'KW', 'LB', 'OM', 'QA', 'SA', 'SY', 'TR', 'YE', 'EG') THEN 'EMEA'
        ELSE (SELECT CASE continent WHEN 'EU' THEN 'EMEA' WHEN 'AF' THEN 'EMEA' WHEN 'AS' THEN 'APAC' WHEN 'OC' THEN 'APAC'
                                    WHEN 'SA' THEN 'LATAM' WHEN 'NA' THEN 'LATAM' ELSE 'Unknown' END
                FROM ref_country_info WHERE iso2 = upper(cc))
    END
$$;

CREATE TABLE metric_refresh (
    name         text PRIMARY KEY,
    refreshed_at timestamptz NOT NULL
);

-- Per tenant and month: MRR with the attributes used to slice it.
CREATE MATERIALIZED VIEW tenant_mrr_monthly AS
WITH months AS (
    SELECT m::date AS month, (m + interval '1 month' - interval '1 day')::date AS month_end
      FROM generate_series(
               (SELECT date_trunc('month', min(start_date)) FROM subscriptions),
               last_complete_month(), interval '1 month') m
)
SELECT m.month, s.tenant_id,
       (array_agg(s.plan_id ORDER BY s.price DESC))[1] AS plan_id,
       (array_agg(s.billing_cycle ORDER BY s.price DESC))[1] AS billing_cycle,
       sum(CASE WHEN s.billing_cycle = 'annual' THEN s.price / 12 ELSE s.price END)::numeric(14, 2) AS mrr,
       t.region, t.industry, t.country_code, t.acquisition_channel
  FROM months m
  JOIN subscriptions s ON s.start_date <= m.month_end AND (s.end_date IS NULL OR s.end_date >= m.month_end)
  JOIN tenants t ON t.id = s.tenant_id
 GROUP BY m.month, s.tenant_id, t.region, t.industry, t.country_code, t.acquisition_channel;
CREATE UNIQUE INDEX tenant_mrr_monthly_ux ON tenant_mrr_monthly (month, tenant_id);
CREATE INDEX tenant_mrr_monthly_tenant_ix ON tenant_mrr_monthly (tenant_id, month);

CREATE MATERIALIZED VIEW mrr_movements AS
WITH months AS (
    SELECT DISTINCT month FROM tenant_mrr_monthly
), pairs AS (
    SELECT m.month, t.tenant_id,
           COALESCE(cur.mrr, 0) AS mrr, COALESCE(prev.mrr, 0) AS prev_mrr,
           COALESCE(cur.plan_id, prev.plan_id) AS plan_id, COALESCE(cur.region, prev.region) AS region,
           COALESCE(cur.industry, prev.industry) AS industry, COALESCE(cur.country_code, prev.country_code) AS country_code,
           COALESCE(cur.acquisition_channel, prev.acquisition_channel) AS acquisition_channel,
           COALESCE(cur.billing_cycle, prev.billing_cycle) AS billing_cycle
      FROM months m
      CROSS JOIN (SELECT DISTINCT tenant_id FROM tenant_mrr_monthly) t
      LEFT JOIN tenant_mrr_monthly cur ON cur.month = m.month AND cur.tenant_id = t.tenant_id
      LEFT JOIN tenant_mrr_monthly prev ON prev.month = (m.month - interval '1 month')::date AND prev.tenant_id = t.tenant_id
)
SELECT month, tenant_id,
       CASE WHEN prev_mrr = 0 AND mrr > 0 THEN 'new'
            WHEN prev_mrr > 0 AND mrr = 0 THEN 'churn'
            WHEN mrr > prev_mrr THEN 'expansion'
            ELSE 'contraction' END AS movement,
       (mrr - prev_mrr)::numeric(14, 2) AS amount,
       plan_id, region, industry, country_code, acquisition_channel, billing_cycle
  FROM pairs WHERE mrr <> prev_mrr;
CREATE UNIQUE INDEX mrr_movements_ux ON mrr_movements (month, tenant_id);
CREATE INDEX mrr_movements_month_ix ON mrr_movements (month, movement);

CREATE MATERIALIZED VIEW mrr_monthly AS
WITH totals AS (
    SELECT month, sum(mrr) AS mrr, count(*) AS customers FROM tenant_mrr_monthly GROUP BY month
), moves AS (
    SELECT month,
           COALESCE(sum(amount) FILTER (WHERE movement = 'new'), 0) AS new_mrr,
           COALESCE(sum(amount) FILTER (WHERE movement = 'expansion'), 0) AS expansion_mrr,
           COALESCE(-sum(amount) FILTER (WHERE movement = 'contraction'), 0) AS contraction_mrr,
           COALESCE(-sum(amount) FILTER (WHERE movement = 'churn'), 0) AS churned_mrr,
           count(*) FILTER (WHERE movement = 'new') AS new_customers,
           count(*) FILTER (WHERE movement = 'churn') AS churned_customers
      FROM mrr_movements GROUP BY month
)
SELECT t.month, t.mrr::numeric(14, 2) AS mrr, (t.mrr * 12)::numeric(16, 2) AS arr, t.customers,
       COALESCE(m.new_mrr, 0)::numeric(14, 2) AS new_mrr, COALESCE(m.expansion_mrr, 0)::numeric(14, 2) AS expansion_mrr,
       COALESCE(m.contraction_mrr, 0)::numeric(14, 2) AS contraction_mrr, COALESCE(m.churned_mrr, 0)::numeric(14, 2) AS churned_mrr,
       (COALESCE(m.new_mrr, 0) + COALESCE(m.expansion_mrr, 0) - COALESCE(m.contraction_mrr, 0) - COALESCE(m.churned_mrr, 0))::numeric(14, 2) AS net_new_mrr,
       COALESCE(m.new_customers, 0) AS new_customers, COALESCE(m.churned_customers, 0) AS churned_customers
  FROM totals t LEFT JOIN moves m ON m.month = t.month;
CREATE UNIQUE INDEX mrr_monthly_ux ON mrr_monthly (month);

-- Trailing twelve month retention: customers that were active twelve months earlier.
--   NRR = their MRR now / their MRR then;  GRR = sum(min(MRR now, MRR then)) / their MRR then.
CREATE MATERIALIZED VIEW retention_monthly AS
SELECT (old.month + interval '12 months')::date AS month,
       (sum(COALESCE(cur.mrr, 0)) / sum(old.mrr))::numeric(8, 4) AS nrr,
       (sum(LEAST(COALESCE(cur.mrr, 0), old.mrr)) / sum(old.mrr))::numeric(8, 4) AS grr,
       count(*) AS base_customers
  FROM tenant_mrr_monthly old
  LEFT JOIN tenant_mrr_monthly cur ON cur.tenant_id = old.tenant_id AND cur.month = (old.month + interval '12 months')::date
 WHERE (old.month + interval '12 months')::date <= last_complete_month()
 GROUP BY 1 HAVING sum(old.mrr) > 0;
CREATE UNIQUE INDEX retention_monthly_ux ON retention_monthly (month);

-- Cohorts by the month of a tenant's first subscription: customers and MRR still active n months later.
CREATE MATERIALIZED VIEW cohort_retention AS
WITH first AS (
    SELECT tenant_id, min(month) AS cohort FROM tenant_mrr_monthly GROUP BY tenant_id
), size AS (
    SELECT f.cohort, count(*) AS cohort_customers, sum(t.mrr) AS cohort_start_mrr
      FROM first f JOIN tenant_mrr_monthly t ON t.tenant_id = f.tenant_id AND t.month = f.cohort GROUP BY f.cohort
)
SELECT f.cohort AS cohort_month,
       ((extract(year FROM t.month) - extract(year FROM f.cohort)) * 12 + extract(month FROM t.month) - extract(month FROM f.cohort))::int AS months_since,
       count(*) AS customers_active, sum(t.mrr)::numeric(14, 2) AS mrr, z.cohort_customers, z.cohort_start_mrr::numeric(14, 2) AS cohort_start_mrr
  FROM first f JOIN tenant_mrr_monthly t ON t.tenant_id = f.tenant_id JOIN size z ON z.cohort = f.cohort
 GROUP BY f.cohort, t.month, z.cohort_customers, z.cohort_start_mrr;
CREATE UNIQUE INDEX cohort_retention_ux ON cohort_retention (cohort_month, months_since);

CREATE MATERIALIZED VIEW revenue_by_dimension AS
SELECT month, 'plan' AS dimension, plan_id AS value, sum(mrr)::numeric(14, 2) AS mrr, count(*) AS customers FROM tenant_mrr_monthly GROUP BY month, plan_id
UNION ALL SELECT month, 'region', COALESCE(region, 'Unknown'), sum(mrr), count(*) FROM tenant_mrr_monthly GROUP BY month, region
UNION ALL SELECT month, 'industry', COALESCE(industry, 'Unknown'), sum(mrr), count(*) FROM tenant_mrr_monthly GROUP BY month, industry
UNION ALL SELECT month, 'channel', COALESCE(acquisition_channel, 'Unknown'), sum(mrr), count(*) FROM tenant_mrr_monthly GROUP BY month, acquisition_channel
UNION ALL SELECT month, 'country', COALESCE(country_code, 'Unknown'), sum(mrr), count(*) FROM tenant_mrr_monthly GROUP BY month, country_code
UNION ALL SELECT month, 'billing_cycle', billing_cycle, sum(mrr), count(*) FROM tenant_mrr_monthly GROUP BY month, billing_cycle;
CREATE UNIQUE INDEX revenue_by_dimension_ux ON revenue_by_dimension (month, dimension, value);

-- Overage is billed on invoices and reported apart from MRR.
CREATE VIEW overage_monthly AS
SELECT date_trunc('month', i.period_start)::date AS month, sum(l.amount)::numeric(14, 2) AS overage
  FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id WHERE l.line_type = 'overage' GROUP BY 1;

-- Unit economics by month.
--   ARPA = MRR / active customers;   logo churn = customers lost / customers at the previous month end
--   quick ratio = (new + expansion) / (contraction + churn)
--   CAC = marketing spend / new customers (also over a trailing three months, which smooths small months)
--   payback months = CAC / (ARPA * gross margin);   LTV = ARPA * gross margin / monthly logo churn (trailing three months)
CREATE VIEW unit_economics_monthly AS
WITH spend AS (
    SELECT month::date AS month, sum(spend) AS spend FROM marketing_spend GROUP BY 1
), base AS (
    SELECT m.month, m.mrr, m.customers, m.new_customers, m.churned_customers, m.new_mrr, m.expansion_mrr, m.contraction_mrr, m.churned_mrr,
           COALESCE(s.spend, 0) AS spend,
           lag(m.customers) OVER (ORDER BY m.month) AS prev_customers
      FROM mrr_monthly m LEFT JOIN spend s ON s.month = m.month
), rolled AS (
    SELECT *,
           sum(spend) OVER w3 AS spend_t3, sum(new_customers) OVER w3 AS new_t3,
           sum(churned_customers) OVER w3 AS churned_t3, sum(prev_customers) OVER w3 AS prev_t3
      FROM base WINDOW w3 AS (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
)
SELECT month, mrr, customers,
       (mrr / NULLIF(customers, 0))::numeric(14, 2) AS arpa,
       (churned_customers::numeric / NULLIF(prev_customers, 0))::numeric(8, 4) AS logo_churn_rate,
       ((new_mrr + expansion_mrr) / NULLIF(contraction_mrr + churned_mrr, 0))::numeric(10, 2) AS quick_ratio,
       spend::numeric(14, 2) AS marketing_spend,
       (spend / NULLIF(new_customers, 0))::numeric(14, 2) AS cac,
       (spend_t3 / NULLIF(new_t3, 0))::numeric(14, 2) AS cac_trailing_3m,
       ((spend_t3 / NULLIF(new_t3, 0)) / NULLIF(mrr / NULLIF(customers, 0) * gross_margin(), 0))::numeric(10, 2) AS payback_months,
       ((mrr / NULLIF(customers, 0)) * gross_margin() / NULLIF(churned_t3::numeric / NULLIF(prev_t3, 0), 0))::numeric(16, 2) AS ltv
  FROM rolled;

-- Row security equivalent for views: only finance analysts and platform administrators see business metrics.
CREATE FUNCTION finance_scope() RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT app_role() IN ('finance_analyst', 'platform_admin')
$$;
GRANT EXECUTE ON FUNCTION finance_scope(), gross_margin(), last_complete_month(), region_of_country(text) TO meridian_app;

CREATE VIEW tenant_mrr_monthly_v AS SELECT * FROM tenant_mrr_monthly WHERE finance_scope();
CREATE VIEW mrr_movements_v AS SELECT * FROM mrr_movements WHERE finance_scope();
CREATE VIEW mrr_monthly_v AS SELECT * FROM mrr_monthly WHERE finance_scope();
CREATE VIEW retention_monthly_v AS SELECT * FROM retention_monthly WHERE finance_scope();
CREATE VIEW cohort_retention_v AS SELECT * FROM cohort_retention WHERE finance_scope();
CREATE VIEW revenue_by_dimension_v AS SELECT * FROM revenue_by_dimension WHERE finance_scope();
CREATE VIEW overage_monthly_v AS SELECT * FROM overage_monthly WHERE finance_scope();
CREATE VIEW unit_economics_monthly_v AS SELECT * FROM unit_economics_monthly WHERE finance_scope();
CREATE VIEW metric_refresh_v AS SELECT * FROM metric_refresh WHERE finance_scope();
GRANT SELECT ON tenant_mrr_monthly_v, mrr_movements_v, mrr_monthly_v, retention_monthly_v, cohort_retention_v,
                revenue_by_dimension_v, overage_monthly_v, unit_economics_monthly_v, metric_refresh_v TO meridian_app;

CREATE FUNCTION refresh_metrics() RETURNS timestamptz LANGUAGE plpgsql AS $$
DECLARE
    now_ts timestamptz := now();
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY tenant_mrr_monthly;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mrr_movements;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mrr_monthly;
    REFRESH MATERIALIZED VIEW CONCURRENTLY retention_monthly;
    REFRESH MATERIALIZED VIEW CONCURRENTLY cohort_retention;
    REFRESH MATERIALIZED VIEW CONCURRENTLY revenue_by_dimension;
    INSERT INTO metric_refresh (name, refreshed_at) VALUES ('metrics', now_ts)
        ON CONFLICT (name) DO UPDATE SET refreshed_at = EXCLUDED.refreshed_at;
    RETURN now_ts;
END
$$;
