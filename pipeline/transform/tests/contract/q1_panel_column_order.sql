-- depends_on: {{ ref('gld_divergence_panel') }}
-- Q1: column names AND order match the contract (the enforced model contract
-- already checks names + types; order is checked here against the YAML order).
{% if execute %}
{% set node = graph.nodes.values() | selectattr('name', 'equalto', 'gld_divergence_panel') | first %}
{% set expected = node.columns.keys() | list %}
with expected as (
    select * from (values {% for c in expected %}('{{ c }}', {{ loop.index }}){{ "," if not loop.last }}{% endfor %}) as e(column_name, position)
),
actual as (
    select column_name, ordinal_position as position
    from information_schema.columns
    where table_schema = '{{ ref("gld_divergence_panel").schema }}' and table_name = 'gld_divergence_panel'
)
select coalesce(e.column_name, a.column_name) as column_name, e.position as expected_position, a.position as actual_position
from expected e full outer join actual a using (column_name)
where e.position is distinct from a.position
{% else %}
select 1 where false
{% endif %}
