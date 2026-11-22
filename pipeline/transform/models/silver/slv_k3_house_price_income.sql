-- K3: house price-to-income ratio index (OECD analytical house prices), SA.
select
    country_iso3                           as country_iso,
    period_start_date                      as quarter_start_date,
    'K3'                                   as indicator_id,
    obs_value                              as value,
    'SA'                                   as sa_status,
    'DF_HOUSE_PRICES ' || country_iso3 || '.Q.HPI_YDH.IX.S' as source_series,
    vintage
from {{ ref('stg_k3_house_price_to_income') }}
where freq = 'Q' and measure = 'HPI_YDH' and adjustment = 'S'
