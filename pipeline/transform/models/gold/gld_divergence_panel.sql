-- THE gold deliverable (DATA_CONTRACT §3): one row per country_iso x quarter,
-- balanced 2010-Q1 .. latest_published_quarter, columns in contract order:
--   7 keys/flags | 21 components (raw, z, idx100 per indicator) | composites | 7 contributions
{% set inds = panel_indicators() %}
with wide as (
    select
        country_iso, quarter, quarter_start_date,
        {% for id, stem in inds %}
        max(case when indicator_id = '{{ id }}' then raw end)       as {{ stem }}_raw,
        max(case when indicator_id = '{{ id }}' then z end)         as {{ stem }}_z,
        max(case when indicator_id = '{{ id }}' then idx100 end)    as {{ stem }}_idx100,
        max(case when indicator_id = '{{ id }}' then contrib_z end) as contrib_{{ id | lower }}_z,
        {% endfor %}
        count(raw)                                                  as n_components_available
    from {{ ref('gld_indicator_scores') }}
    group by 1, 2, 3
),
flagged as (
    select
        *,
        n_components_available = {{ inds | length }}               as is_complete
    from wide
),
latest as (
    select
        *,
        max(case when is_complete then quarter_start_date end) over (partition by country_iso) as latest_complete_q
    from flagged
),
common as (
    select *, min(latest_complete_q) over () as latest_complete_common_q from latest
)
select
    -- 3.1 keys & flags
    cast(country_iso as varchar)                                               as country_iso,
    cast(quarter as varchar)                                                   as quarter,
    cast(quarter_start_date as date)                                           as quarter_start_date,
    quarter_start_date between date '{{ var("baseline_start") }}' and date '{{ var("baseline_end") }}' as is_baseline_window,
    is_complete,
    coalesce(is_complete and quarter_start_date <= latest_complete_common_q, false) as is_composite_eligible,
    cast(n_components_available as integer)                                    as n_components_available,
    -- 3.2 components
    {% for id, stem in inds %}
    cast({{ stem }}_raw as double) as {{ stem }}_raw,
    cast({{ stem }}_z as double) as {{ stem }}_z,
    cast({{ stem }}_idx100 as double) as {{ stem }}_idx100,
    {% endfor %}
    -- 3.3 composites: null if ANY component is null (no partial composites)
    cast((h1_real_gdp_pc_z + h2_real_equity_z + h3_unemployment_z) / 3 as double)                               as headline_z,
    cast((k1_real_hhdi_pc_z + k2_hh_dsr_z + k3_house_price_income_z + k4_essentials_cpi_z) / 4 as double)       as kitchen_table_z,
    cast((h1_real_gdp_pc_z + h2_real_equity_z + h3_unemployment_z) / 3
       - (k1_real_hhdi_pc_z + k2_hh_dsr_z + k3_house_price_income_z + k4_essentials_cpi_z) / 4 as double)       as divergence_gap_z,
    {% if var('include_idx100_composites') %}
    cast((h1_real_gdp_pc_idx100 + h2_real_equity_idx100 + h3_unemployment_idx100) / 3 as double)               as headline_idx100,
    cast((k1_real_hhdi_pc_idx100 + k2_hh_dsr_idx100 + k3_house_price_income_idx100 + k4_essentials_cpi_idx100) / 4 as double) as kitchen_table_idx100,
    cast((h1_real_gdp_pc_idx100 + h2_real_equity_idx100 + h3_unemployment_idx100) / 3
       - (k1_real_hhdi_pc_idx100 + k2_hh_dsr_idx100 + k3_house_price_income_idx100 + k4_essentials_cpi_idx100) / 4 as double) as divergence_gap_idx100,
    {% endif %}
    -- 3.4 additive contributions (sum to divergence_gap_z)
    {% for id, stem in inds %}
    cast(contrib_{{ id | lower }}_z as double) as contrib_{{ id | lower }}_z{{ "," if not loop.last }}
    {% endfor %}
from common
order by country_iso, quarter_start_date
