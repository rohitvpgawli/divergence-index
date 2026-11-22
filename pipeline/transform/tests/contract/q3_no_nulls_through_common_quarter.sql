-- Q3: zero null components from 2010-Q1 through latest_complete_common_quarter
-- (no baseline_window_override entries exist in v1).
with common as (
    select max(quarter_start_date) as q from {{ ref('gld_divergence_panel') }} where is_composite_eligible
)
select country_iso, quarter, n_components_available
from {{ ref('gld_divergence_panel') }}, common
where quarter_start_date <= common.q and n_components_available < 7
