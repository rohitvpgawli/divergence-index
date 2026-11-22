-- H1: real GDP per capita = GDP chain-linked volume (national currency, SA,
-- quarterly level, expenditure table T0102) / population (same series as K1, D4).
with gdp as (
    select country_iso3, period_start_date, obs_value * pow(10, unit_mult) as gdp, vintage
    from {{ ref('stg_ref_gdp_volume') }}
    where freq = 'Q' and price_base = 'L' and transformation = 'N' and adjustment = 'Y'
)
select
    g.country_iso3                         as country_iso,
    g.period_start_date                    as quarter_start_date,
    'H1'                                   as indicator_id,
    g.gdp / p.population                   as value,
    'SA'                                   as sa_status,
    'DF_QNA Q.Y.' || g.country_iso3 || '.S1.S1.B1GQ._Z._Z._Z.XDC.L.N.T0102 / ' || p.source_series as source_series,
    g.vintage
from gdp g
join {{ ref('slv_population') }} p
  on p.country_iso = g.country_iso3 and p.quarter_start_date = g.period_start_date
