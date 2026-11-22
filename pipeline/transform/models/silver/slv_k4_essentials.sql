-- K4: essentials burden.
--   1. Food (CP01) and energy (CP045_0722) CPI, quarterly. Per country ONE frequency
--      for the whole history: monthly (3-month average) if monthly data reaches back to
--      2010-01, else OECD's own quarterly series (AUS: monthly only exists from 2024).
--   2. Rebase each to 2015 = 100.
--   3. Combine with fixed national basket weights, averaged over var('cpi_weight_years')
--      (contract D2): w_food = W_food / (W_food + W_energy).
--   4. var('k4_definition'):
--        income_ratio (methodology v0.1) -> food & energy index / nominal household
--                                          income per capita index (2015 = 100) x 100
--        price_level  (contract draft)   -> food & energy index
{% set components = ['CP01', 'CP045_0722'] %}
with raw_cpi as (
    select country_iso3, expenditure, freq, period_start_date, obs_value
    from {{ ref('stg_k4_cpi_components') }}
    where expenditure in ('CP01', 'CP045_0722') and freq in ('M', 'Q')
      and measure = 'CPI' and adjustment = 'N'
),
freq_choice as (     -- monthly only if BOTH components start by 2010-01
    select country_iso3,
           case when count(distinct case when freq = 'M' and period_start_date <= date '{{ var("panel_start") }}' then expenditure end) = 2
                then 'M' else 'Q' end as freq
    from raw_cpi group by 1
),
quarterly as (
    select r.country_iso3, r.expenditure, cast(date_trunc('quarter', r.period_start_date) as date) as quarter_start_date,
           avg(r.obs_value) as value, f.freq
    from raw_cpi r join freq_choice f on r.country_iso3 = f.country_iso3 and r.freq = f.freq
    group by all
    having f.freq = 'Q' or count(distinct month(r.period_start_date)) = 3
),
rebased as (
    select q.*, q.value / avg(case when year(q.quarter_start_date) = 2015 then q.value end)
                    over (partition by q.country_iso3, q.expenditure) * 100 as idx_2015
    from quarterly q
),
weights as (
    select country_iso3,
           avg(case when expenditure = 'CP01' then obs_value end) as w_food_raw,
           avg(case when expenditure = 'CP045_0722' then obs_value end) as w_energy_raw
    from {{ ref('stg_ref_cpi_weights') }}
    where time_period in ({{ "'" ~ var('cpi_weight_years') | join("', '") ~ "'" }})
    group by 1
),
fe as (
    select r.country_iso3, r.quarter_start_date, any_value(r.freq) as cpi_freq,
           any_value(w.w_food_raw / (w.w_food_raw + w.w_energy_raw)) as w_food,
           max(case when r.expenditure = 'CP01' then r.idx_2015 end)       as food_idx,
           max(case when r.expenditure = 'CP045_0722' then r.idx_2015 end) as energy_idx
    from rebased r join weights w using (country_iso3)
    group by 1, 2
),
income_pc as (
    select i.country_iso, i.quarter_start_date, i.sa_status,
           (i.hh_income_nominal / p.population)
             / avg(case when year(i.quarter_start_date) = 2015 then i.hh_income_nominal / p.population end)
               over (partition by i.country_iso) * 100 as income_idx_2015
    from {{ ref('slv_hh_income_nominal') }} i
    join {{ ref('slv_population') }} p using (country_iso, quarter_start_date)
)
select
    f.country_iso3                                                as country_iso,
    f.quarter_start_date,
    'K4'                                                          as indicator_id,
    {% if var('k4_definition') == 'income_ratio' %}
    (f.w_food * f.food_idx + (1 - f.w_food) * f.energy_idx) / ip.income_idx_2015 * 100
    {% elif var('k4_definition') == 'price_level' %}
    (f.w_food * f.food_idx + (1 - f.w_food) * f.energy_idx)
    {% else %}
    {{ exceptions.raise_compiler_error("k4_definition must be income_ratio or price_level") }}
    {% endif %}                                                   as value,
    'NSA'                                                         as sa_status,
    'DF_PRICES_ALL ' || f.country_iso3 || '.' || f.cpi_freq || '.N.CPI.IX.CP01+CP045_0722.N._Z (w_food='
        || round(f.w_food, 4) || ')'
        {% if var('k4_definition') == 'income_ratio' %} || ' / DF_QSA B6G per capita'{% endif %} as source_series,
    (select max(vintage) from {{ ref('stg_k4_cpi_components') }})  as vintage,
    -- audit columns (not part of the long fact)
    f.food_idx, f.energy_idx, f.w_food, f.cpi_freq
    {% if var('k4_definition') == 'income_ratio' %}, ip.income_idx_2015{% endif %}
from fe f
{% if var('k4_definition') == 'income_ratio' %}
join income_pc ip on ip.country_iso = f.country_iso3 and ip.quarter_start_date = f.quarter_start_date
{% endif %}
where f.food_idx is not null and f.energy_idx is not null
