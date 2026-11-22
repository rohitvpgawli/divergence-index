-- H2: real equity = quarterly average of the monthly national share price index
-- / quarterly average of BIS headline CPI x 100 (contract D5, D7).
with shares as (
    {{ monthly_to_quarterly("select country_iso3, period_start_date, obs_value from " ~ ref('stg_h2_share_price_index') ~ " where freq = 'M'") }}
),
cpi as (
    {{ monthly_to_quarterly("select country_iso3, period_start_date, obs_value from " ~ ref('stg_ref_headline_cpi_bis') ~ " where freq = 'M'") }}
),
vintages as (
    select greatest(
        (select max(vintage) from {{ ref('stg_h2_share_price_index') }}),
        (select max(vintage) from {{ ref('stg_ref_headline_cpi_bis') }})) as vintage
)
select
    s.country_iso3                         as country_iso,
    s.quarter_start_date,
    'H2'                                   as indicator_id,
    s.value / c.value * 100                as value,
    'n/a'                                  as sa_status,
    'DF_FINMARK ' || s.country_iso3 || '.M.SHARE.IX._Z._Z._Z._Z.N / WS_LONG_CPI M.' || cc.iso2 || '.628' as source_series,
    v.vintage
from shares s
join cpi c using (country_iso3, quarter_start_date)
join {{ ref('countries') }} cc on cc.iso3 = s.country_iso3
cross join vintages v
