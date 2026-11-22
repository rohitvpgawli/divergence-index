-- Nominal gross disposable income of households + NPISH (S1M, B6G), national
-- currency, quarterly level (transformation N, not annualised).
-- Seasonally adjusted where OECD publishes it (USA, CAN, GBR, DEU, AUS);
-- JPN and KOR exist only NSA -> taken as-is and flagged in sa_status.
-- Accounting entries C and D carry identical values for this balancing item; C is used.
with candidates as (
    select
        country_iso3, period_start_date, obs_value * pow(10, unit_mult) as value, adjustment, vintage
    from {{ ref('stg_k1_hh_disposable_income_nominal') }}
    where freq = 'Q' and transformation = 'N' and accounting_entry = 'C'
),
preferred as (   -- per country: SA if it exists at all, else NSA
    select country_iso3, max(case when adjustment = 'Y' then 'Y' else 'N' end) as adj
    from candidates group by 1
)
select
    c.country_iso3                                         as country_iso,
    c.period_start_date                                    as quarter_start_date,
    c.value                                                as hh_income_nominal,
    case when p.adj = 'Y' then 'SA' else 'NSA' end         as sa_status,
    'DF_QSA Q.' || p.adj || '.' || c.country_iso3 || '.S1M...B6G (C, N)' as source_series,
    c.vintage
from candidates c
join preferred p on c.country_iso3 = p.country_iso3 and c.adjustment = p.adj
