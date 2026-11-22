{# 'YYYY-Qn' label for a date (contract §2 time key) #}
{% macro quarter_label(d) -%}
    (strftime({{ d }}, '%Y') || '-Q' || quarter({{ d }}))
{%- endmacro %}

{# Quarter index used for detrending: 0 = baseline start quarter #}
{% macro quarter_index(d) -%}
    ((year({{ d }}) - year(date '{{ var("baseline_start") }}')) * 4 + quarter({{ d }}) - quarter(date '{{ var("baseline_start") }}'))
{%- endmacro %}

{#
  Monthly -> quarterly arithmetic mean, ONLY for quarters with all 3 months
  present (contract §5: no 1- or 2-month averages).
  `relation_sql` must expose: country_iso3, period_start_date, obs_value.
#}
{% macro monthly_to_quarterly(relation_sql) -%}
    select
        country_iso3,
        cast(date_trunc('quarter', period_start_date) as date) as quarter_start_date,
        avg(obs_value)                                          as value,
        count(*)                                                as n_months
    from ({{ relation_sql }}) m
    where obs_value is not null
    group by 1, 2
    having count(distinct month(period_start_date)) = 3
{%- endmacro %}
