-- Quarterly population (persons), seasonally adjusted. ONE series used as the
-- per-capita denominator for H1, K1 and K4 (contract D4).
select
    country_iso3                               as country_iso,
    period_start_date                          as quarter_start_date,
    obs_value * pow(10, unit_mult)             as population,
    'DF_QNA_POP_EMPNC Q.Y.' || country_iso3 || '.S1.S1.POP' as source_series,
    vintage
from {{ ref('stg_ref_population') }}
where freq = 'Q' and transaction = 'POP' and adjustment = 'Y'
