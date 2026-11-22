-- Per country x indicator, estimated ONLY on the reference window
-- (var baseline_start..baseline_end, 2010-Q1..2019-Q4) and then held fixed.
--   level      (H3, K2, K3, K4): mean mu and sample SD sigma of the value
--   detrended  (H1, H2, K1):     OLS fit ln(value) = alpha + beta * t, sigma = sample SD
--                                of the residuals (ddof = 1, contract Q5)
with base as (
    select
        s.country_iso, s.indicator_id, d.treatment,
        {{ quarter_index('s.quarter_start_date') }} as t,
        case when d.treatment = 'detrended' then ln(s.value) else s.value end as y
    from {{ ref('slv_indicator_quarterly') }} s
    join {{ ref('dim_indicator') }} d using (indicator_id)
    where s.quarter_start_date between date '{{ var("baseline_start") }}' and date '{{ var("baseline_end") }}'
),
fit as (
    select
        country_iso, indicator_id, any_value(treatment) as treatment,
        count(*)                                     as n_quarters,
        avg(y)                                       as mean_y,
        stddev_samp(y)                               as sd_y,
        regr_intercept(y, t)                         as alpha,
        regr_slope(y, t)                             as beta
    from base group by 1, 2
),
resid as (
    select b.country_iso, b.indicator_id, stddev_samp(b.y - (f.alpha + f.beta * b.t)) as sd_resid
    from base b join fit f using (country_iso, indicator_id)
    group by 1, 2
)
select
    f.country_iso,
    f.indicator_id,
    f.treatment,
    f.n_quarters,
    case when f.treatment = 'level' then f.mean_y end         as mean,
    case when f.treatment = 'detrended' then f.alpha end      as trend_alpha,
    case when f.treatment = 'detrended' then f.beta end       as trend_beta,
    case when f.treatment = 'detrended' then r.sd_resid else f.sd_y end as sigma
from fit f join resid r using (country_iso, indicator_id)
