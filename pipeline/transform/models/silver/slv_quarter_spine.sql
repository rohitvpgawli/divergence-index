-- Balanced panel skeleton: every country x every quarter from var('panel_start')
-- to latest_published_quarter (latest quarter with ANY value for ANY country,
-- contract §5). Rows exist even when every value is null (contract §2).
with bounds as (
    select date '{{ var("panel_start") }}' as first_q,
           max(quarter_start_date)          as last_q
    from {{ ref('slv_indicator_quarterly') }}
),
quarters as (
    select cast(q as date) as quarter_start_date
    from bounds, generate_series(first_q, last_q, interval 3 month) as t(q)
)
select
    c.iso3                                    as country_iso,
    q.quarter_start_date,
    {{ quarter_label('q.quarter_start_date') }} as quarter
from {{ ref('countries') }} c
cross join quarters q
