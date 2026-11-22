-- Warning only (contract §7): any |z| > 6. Expected for shocks like 2020-Q2 on smooth
-- series (methodology §4c); listed so the narrative can caveat them.
{{ config(severity = 'warn') }}
select country_iso, quarter, indicator_id, round(z, 2) as z
from {{ ref('gld_indicator_scores') }}
where abs(z) > 6
