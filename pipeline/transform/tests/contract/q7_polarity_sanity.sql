-- Q7: polarity sanity per country x indicator.
--   level indicators:     corr(raw, z) has the sign of the polarity (negative for H3, K2, K3, K4)
--   detrended indicators: corr(detrended ln raw, z) has the sign of the polarity (positive for H1, H2, K1)
--   (raw-vs-z is not meaningful for detrended series: raw trends, z does not; see DATA_CONTRACT_REVIEW §2c)
with s as (
    select sc.country_iso, sc.indicator_id, d.polarity, d.treatment, sc.raw, sc.z,
           case when d.treatment = 'detrended'
                then ln(sc.raw) - (b.trend_alpha + b.trend_beta * {{ quarter_index('sc.quarter_start_date') }})
                else sc.raw end as x
    from {{ ref('gld_indicator_scores') }} sc
    join {{ ref('dim_indicator') }} d using (indicator_id)
    join {{ ref('gld_baseline_stats') }} b using (country_iso, indicator_id)
    where sc.z is not null
)
select country_iso, indicator_id, polarity, corr(x, z) as correlation
from s group by 1, 2, 3
having sign(corr(x, z)) <> polarity
