-- Long scores: one row per country x quarter x indicator on the balanced spine.
--   raw     native units / direction (silver)
--   z       Model 1: s_k * (x - mu)/sigma, or s_k * (ln x - (alpha + beta t))/sigma_e
--   idx100  Model 2: x / x_2019Q4 * 100, inverted indicators 200 - (...)
--   contrib w_k * sign_in_gap * z  (+1/3 headline, -1/4 kitchen table): sums to the gap
with dims as (
    select d.*, 1.0 / count(*) over (partition by basket) as weight
    from {{ ref('dim_indicator') }} d
),
grid as (
    select sp.country_iso, sp.quarter_start_date, sp.quarter, d.indicator_id, d.basket, d.polarity,
           d.sign_in_gap, d.weight, d.treatment, d.ordinal
    from {{ ref('slv_quarter_spine') }} sp cross join dims d
),
anchor as (
    select country_iso, indicator_id, value as anchor_value
    from {{ ref('slv_indicator_quarterly') }}
    where quarter_start_date = date '{{ var("idx100_anchor") }}'
),
scored as (
    select
        g.*,
        s.value                                       as raw,
        s.sa_status, s.source_series, s.vintage,
        b.mean, b.trend_alpha, b.trend_beta, b.sigma,
        a.anchor_value,
        -- "+ 0.0" turns IEEE negative zero (-1 x 0.0) into 0.0 so outputs never print "-0.0"
        0.0 + case when g.treatment = 'detrended'
             then g.polarity * (ln(s.value) - (b.trend_alpha + b.trend_beta * {{ quarter_index('g.quarter_start_date') }})) / b.sigma
             else g.polarity * (s.value - b.mean) / b.sigma
        end                                           as z,
        case when g.polarity = 1 then s.value / a.anchor_value * 100
             else 200 - s.value / a.anchor_value * 100
        end                                           as idx100
    from grid g
    left join {{ ref('slv_indicator_quarterly') }} s
           on s.country_iso = g.country_iso and s.quarter_start_date = g.quarter_start_date
          and s.indicator_id = g.indicator_id
    left join {{ ref('gld_baseline_stats') }} b on b.country_iso = g.country_iso and b.indicator_id = g.indicator_id
    left join anchor a on a.country_iso = g.country_iso and a.indicator_id = g.indicator_id
)
select
    country_iso, quarter_start_date, quarter, indicator_id, basket, ordinal,
    raw, z, idx100,
    0.0 + sign_in_gap * weight * z                    as contrib_z,
    sa_status, source_series, vintage
from scored
