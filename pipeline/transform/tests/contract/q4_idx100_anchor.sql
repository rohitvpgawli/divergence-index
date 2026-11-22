-- Q4: every *_idx100 equals 100 at 2019-Q4 (tolerance 1e-9).
select country_iso, indicator_id, idx100
from {{ ref('gld_indicator_scores') }}
where quarter_start_date = date '{{ var("idx100_anchor") }}'
  and (idx100 is null or abs(idx100 - 100) > 1e-9)
