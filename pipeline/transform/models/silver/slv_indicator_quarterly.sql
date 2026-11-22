-- The silver long fact: ONE value per country x quarter x indicator, in native units
-- and native direction (these become the contract's *_raw columns).
{% set models = ['slv_h1_real_gdp_pc', 'slv_h2_real_equity', 'slv_h3_unemployment',
                 'slv_k1_real_hhdi_pc', 'slv_k2_hh_dsr', 'slv_k3_house_price_income', 'slv_k4_essentials'] %}
with unioned as (
{% for m in models %}
    select country_iso, quarter_start_date, indicator_id, value, sa_status, source_series, vintage
    from {{ ref(m) }}
    {% if not loop.last %}union all{% endif %}
{% endfor %}
)
select
    country_iso,
    quarter_start_date,
    {{ quarter_label('quarter_start_date') }} as quarter,
    indicator_id,
    value,
    sa_status,
    source_series,
    vintage
from unioned
where value is not null
  and quarter_start_date >= date '{{ var("panel_start") }}' - interval 1 year   -- keep 2009 for context
