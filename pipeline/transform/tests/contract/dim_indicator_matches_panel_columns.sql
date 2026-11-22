-- Guard: the panel's column list (macro panel_indicators) and the dim_indicator seed agree.
with macro_list as (
    select * from (values {% for id, stem in panel_indicators() %}('{{ id }}', '{{ stem }}', {{ loop.index }}){{ "," if not loop.last }}{% endfor %}) as m(indicator_id, column_stem, ordinal)
)
select coalesce(m.indicator_id, d.indicator_id) as indicator_id
from macro_list m full outer join {{ ref('dim_indicator') }} d using (indicator_id)
where m.column_stem is distinct from d.column_stem or m.ordinal is distinct from d.ordinal
