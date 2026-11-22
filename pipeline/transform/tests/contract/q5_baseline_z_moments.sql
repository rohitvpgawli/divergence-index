-- Q5: over the baseline window every z has mean ~0 (|mu| < 1e-6) and SD ~1
-- (|sigma - 1| < 1e-6), ddof = 1, per country x indicator.
select country_iso, indicator_id, count(z) as n, avg(z) as mean_z, stddev_samp(z) as sd_z
from {{ ref('gld_indicator_scores') }}
where quarter_start_date between date '{{ var("baseline_start") }}' and date '{{ var("baseline_end") }}'
group by 1, 2
having count(z) <> 40 or abs(avg(z)) >= 1e-6 or abs(stddev_samp(z) - 1) >= 1e-6
