-- Q2: (country_iso, quarter) unique and non-null; balanced panel = 7 x N quarters.
with dup as (
    select country_iso, quarter from {{ ref('gld_divergence_panel') }}
    group by 1, 2 having count(*) > 1 or country_iso is null or quarter is null
),
shape as (
    select count(*) as n_rows, count(distinct country_iso) as n_cty, count(distinct quarter) as n_q
    from {{ ref('gld_divergence_panel') }}
)
select 'duplicate or null key' as issue, country_iso || ' ' || quarter as detail from dup
union all
select 'unbalanced panel', n_rows || ' rows vs ' || n_cty || ' x ' || n_q from shape where n_rows <> n_cty * n_q or n_cty <> 7
