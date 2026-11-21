{# One observation per series per period: fails if any combination of the
   given columns appears more than once. #}
{% test unique_series_observation(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by all
having count(*) > 1
{% endtest %}
