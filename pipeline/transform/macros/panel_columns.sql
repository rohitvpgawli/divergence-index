{# Single source of truth for the gold panel's indicator columns, in contract order.
   (dim_indicator holds the same stems; a test checks they agree.) #}
{% macro panel_indicators() %}
    {{ return([
        ('H1', 'h1_real_gdp_pc'), ('H2', 'h2_real_equity'), ('H3', 'h3_unemployment'),
        ('K1', 'k1_real_hhdi_pc'), ('K2', 'k2_hh_dsr'), ('K3', 'k3_house_price_income'), ('K4', 'k4_essentials_cpi')
    ]) }}
{% endmacro %}
