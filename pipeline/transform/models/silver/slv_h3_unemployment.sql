-- H3: harmonised unemployment rate, % of labour force, SA; quarterly average of
-- the three monthly values (complete quarters only).
with q as (
    {{ monthly_to_quarterly("select country_iso3, period_start_date, obs_value from " ~ ref('stg_h3_unemployment_rate') ~ " where freq = 'M'") }}
)
select
    country_iso3                           as country_iso,
    quarter_start_date,
    'H3'                                   as indicator_id,
    value,
    'SA'                                   as sa_status,
    'DF_IALFS_UNE_M ' || country_iso3 || '.UNE_LF_M.PT_LF_SUB._Z.Y._T.Y_GE15._Z.M' as source_series,
    (select max(vintage) from {{ ref('stg_h3_unemployment_rate') }}) as vintage
from q
