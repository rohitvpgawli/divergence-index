{#
  Shared staging logic for every SDMX bronze table (OECD and BIS).

  What it does (and only this; no methodology calculations):
    1. keep only the latest sync (Airbyte S3: the sync-start epoch in the file
       name, e.g. 2026_11_22_1795369809600_0.parquet; local: the vintage= folder)
    2. cast obs_value from string to DOUBLE (empty string -> NULL)
    3. map BIS ISO-2 codes to ISO-3 via the `countries` seed
    4. turn SDMX period labels (2024-Q3, 2024-07, 2024) into a period_start_date
    5. expose the series-identifying dimensions from the raw source row
#}
{% macro stg_sdmx(stream) %}
with all_syncs as (
    select
        *,
        {{ bronze_sync_id() }} as _sync_id
    from {{ source('bronze', stream) }}
),
src as (
    select
        * {% if var('bronze_source') != 's3' %}exclude (vintage){% endif %},
        cast(timezone('UTC', to_timestamp(_sync_id / 1000)) as date) as vintage   -- UTC date of the sync
    from all_syncs
    where _sync_id = (select max(_sync_id) from all_syncs)
),
countries as (
    select * from {{ ref('countries') }}
)
select
    src.source,
    src.indicator_id,
    c.iso3                                                   as country_iso3,
    src.freq,
    src.time_period,
    case
        when src.time_period like '____-Q_' then
            make_date(cast(left(src.time_period, 4) as int),
                      (cast(right(src.time_period, 1) as int) - 1) * 3 + 1, 1)
        when src.time_period like '____-__' then cast(src.time_period || '-01' as date)
        when src.time_period like '____'    then make_date(cast(src.time_period as int), 1, 1)
    end                                                      as period_start_date,
    try_cast(nullif(src.obs_value, '') as double)            as obs_value,
    nullif(src.obs_status, '')                               as obs_status,
    nullif(src.unit_measure, '')                             as unit_measure,
    json_extract_string(src.raw, '$.ADJUSTMENT')             as adjustment,
    json_extract_string(src.raw, '$.SECTOR')                 as sector,
    json_extract_string(src.raw, '$.ACCOUNTING_ENTRY')       as accounting_entry,
    json_extract_string(src.raw, '$.TRANSACTION')            as transaction,
    json_extract_string(src.raw, '$.PRICE_BASE')             as price_base,
    json_extract_string(src.raw, '$.EXPENDITURE')            as expenditure,
    json_extract_string(src.raw, '$.MEASURE')                as measure,
    json_extract_string(src.raw, '$.TRANSFORMATION')         as transformation,   -- N = quarterly level, LA = annualised
    nullif(json_extract_string(src.raw, '$.REF_YEAR_PRICE'), '') as ref_year_price,
    json_extract_string(src.raw, '$.TABLE_IDENTIFIER')       as table_identifier,
    src.dataflow,
    src._sync_id                                             as sync_id,
    src.vintage
from src
join countries c
  on src.ref_area = c.iso3 or src.ref_area = c.iso2
{% endmacro %}

{#
  Identifies which ingestion run a bronze row came from, as epoch milliseconds,
  so "latest" means one complete pull and never a mix of two.
    s3:    Airbyte names files <YYYY_MM_DD>_<sync start epoch ms>_<part>.parquet
    local: PyAirbyte writes data/bronze/<stream>/vintage=<YYYY-MM-DD>/
#}
{% macro bronze_sync_id() %}
    {%- if var('bronze_source') == 's3' -%}
        cast(regexp_extract(filename, '_(\d{13})_\d+\.parquet$', 1) as bigint)
    {%- else -%}
        epoch_ms(cast(vintage as date))
    {%- endif -%}
{% endmacro %}
