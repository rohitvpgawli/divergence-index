-- Q6: the seven additive contributions sum to divergence_gap_z (tolerance 1e-9)
-- on every composite-eligible row.
select country_iso, quarter, divergence_gap_z,
       contrib_h1_z + contrib_h2_z + contrib_h3_z + contrib_k1_z + contrib_k2_z + contrib_k3_z + contrib_k4_z as contrib_sum
from {{ ref('gld_divergence_panel') }}
where is_composite_eligible
  and (divergence_gap_z is null
       or abs(contrib_h1_z + contrib_h2_z + contrib_h3_z + contrib_k1_z + contrib_k2_z + contrib_k3_z + contrib_k4_z - divergence_gap_z) > 1e-9)
