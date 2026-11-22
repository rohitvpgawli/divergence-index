-- Household final consumption deflator = current prices (V) / chain-linked volume (L),
-- households (S14), domestic concept (P31DC), quarterly level. Index ~1 in the
-- volume reference year. Per country: SA when BOTH V and L exist SA (6 countries);
-- JPN has no SA current-price series, so both legs are NSA there.
with base as (
    select country_iso3, period_start_date, adjustment, price_base, obs_value * pow(10, unit_mult) as value, vintage
    from {{ ref('stg_ref_hh_consumption') }}
    where freq = 'Q' and sector = 'S14' and transformation = 'N' and price_base in ('V', 'L')
),
legs as (
    select country_iso3, adjustment, count(distinct price_base) as n_legs from base group by 1, 2
),
preferred as (
    select country_iso3, max(case when adjustment = 'Y' and n_legs = 2 then 'Y' else 'N' end) as adj
    from legs group by 1
),
pivoted as (
    select
        b.country_iso3, b.period_start_date, p.adj,
        max(case when price_base = 'V' then value end) as current_prices,
        max(case when price_base = 'L' then value end) as volume,
        max(b.vintage) as vintage
    from base b join preferred p on b.country_iso3 = p.country_iso3 and b.adjustment = p.adj
    group by all
)
select
    country_iso3                                       as country_iso,
    period_start_date                                  as quarter_start_date,
    current_prices / volume                            as deflator,
    case when adj = 'Y' then 'SA' else 'NSA' end       as sa_status,
    'DF_QNA Q.' || adj || '.' || country_iso3 || '.S14.S1.P31DC (V / L)' as source_series,
    vintage
from pivoted
where current_prices is not null and volume is not null
