-- K2: household debt service ratio (BIS), % of disposable income, quarterly, NSA.
select
    country_iso3                           as country_iso,
    period_start_date                      as quarter_start_date,
    'K2'                                   as indicator_id,
    obs_value                              as value,
    'NSA'                                  as sa_status,
    'WS_DSR Q.' || (select iso2 from {{ ref('countries') }} c where c.iso3 = s.country_iso3) || '.H' as source_series,
    vintage
from {{ ref('stg_k2_household_dsr') }} s
where freq = 'Q'
