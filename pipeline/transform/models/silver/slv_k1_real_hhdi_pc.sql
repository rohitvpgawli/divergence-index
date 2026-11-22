-- K1: real household disposable income per capita
--   = nominal household income / household consumption deflator / population.
-- Built identically for all 7 (KOR is not in the OECD Household Dashboard; D3).
select
    i.country_iso,
    i.quarter_start_date,
    'K1'                                   as indicator_id,
    i.hh_income_nominal / d.deflator / p.population as value,
    case when i.sa_status = 'SA' and d.sa_status = 'SA' then 'SA' else 'NSA' end as sa_status,
    i.source_series || ' / ' || d.source_series || ' / ' || p.source_series as source_series,
    greatest(i.vintage, d.vintage, p.vintage) as vintage
from {{ ref('slv_hh_income_nominal') }} i
join {{ ref('slv_hh_consumption_deflator') }} d using (country_iso, quarter_start_date)
join {{ ref('slv_population') }} p using (country_iso, quarter_start_date)
