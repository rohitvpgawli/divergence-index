# How the Airbyte connectors were built

A walkthrough of `pipeline/ingest/airbyte/manifests/`: what an Airbyte connector is, how these two were built step by step, and how to add a new series yourself.

---

## 1. The mental model

Airbyte splits ingestion into three parts:

| Airbyte term | Meaning | In this project |
| --- | --- | --- |
| **Source** (connector) | Knows how to talk to one API | `source-oecd-sdmx`, `source-bis-sdmx` |
| **Stream** | One table the source can emit | `k2_household_dsr`, `h3_unemployment_rate`, … |
| **Record** | One row in a stream | one observation: country × period × value |
| **Destination** | Where the records land | the DuckDB cache, then Parquet in `data/bronze/` |

There are two ways to write a source:

- **Python CDK**: you write classes in Python. Use it only for unusual APIs.
- **Declarative / low-code**: you describe the API in **YAML** (the "manifest"), and Airbyte's engine (the CDK) does the HTTP calls, retries, decoding and schema handling. **This is what we used.** It's the same format the Connector Builder UI in Airbyte Cloud/OSS produces, so these files can be pasted into it unchanged.

There are also three ways to *run* a connector:

| Option | Needs | Why we didn't / did use it |
| --- | --- | --- |
| Airbyte Cloud | a paid account | Not needed for a public-data project |
| Airbyte OSS (`abctl`) | Docker + a Kubernetes-in-Docker server | No Docker on the Mac; too heavy for a monthly GitHub Action |
| **PyAirbyte** (`pip install airbyte`) | Python only | Runs the same manifest in-process and writes to DuckDB. Works in GitHub Actions. ✅ |

---

## 2. How the connectors were built: the five steps

### Step 1: Find the dataset (the "dataflow")

SDMX is the standard API that statistics agencies (OECD, BIS, ECB, IMF) use. Data lives in **dataflows**, and every dataflow has an ID of the form `AGENCY,DSD@FLOW,VERSION`.

To find the right one, list every dataflow and search it:

```bash
curl -s "https://sdmx.oecd.org/public/rest/dataflow/all" -o flows.xml
grep -oE 'Dataflow id="[^"]+" agencyID="[^"]+"' flows.xml | grep -i HOUSE
# -> DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES, agency OECD.ECO.MPD
```

### Step 2: Work out the series key

SDMX data URLs look like `/data/{dataflow}/{key}`. The key is the dimension values joined by dots, **in the dataflow's own order**. An empty slot means "everything", and `+` means OR.

The fastest way to learn the dimensions is to guess, and let the API's error message tell you how many there are:

```bash
curl ".../data/OECD.SDD.NAD,DSD_HHDASH@DF_HHDASH_INDIC,1.1/USA"
# -> "Not enough key values in query, expecting 4 got 1"
```

Next, query with wildcards for a short recent window and look at which combinations come back:

```bash
curl ".../DF_HHDASH_INDIC,1.1/.USA..?startPeriod=2024&format=csvfilewithlabels"
# -> FREQ=Q | REF_AREA=USA | MEASURE=B6GS1M_R_POP (Real gross disposable income per capita...)
```

`csvfilewithlabels` adds human-readable labels next to the codes, which is how you pick the right `MEASURE`, `ADJUSTMENT` and so on. Then pin those codes into the key: `Q.{countries}.B6GS1M_R_POP.`

### Step 3: Check coverage with plain `curl` before writing any YAML

Query all 7 countries from 2009 and count periods for each country. This is where we found the gaps listed in `docs/DATA_SOURCES.md`, such as Korea missing from the Household Dashboard and Japan's CPI stopping in 2021. **Always do this first.** It's much faster than debugging through Airbyte.

### Step 4: Write the stream in the manifest

Shared logic goes in `definitions`, and each stream only overrides its parameters (see section 3).

### Step 5: Run, read the error, fix

```bash
uv run python pipeline/ingest/run_ingest.py --source bis
```

The first run failed with `'utf-8' codec can't decode byte 0x8b`. `0x8b` is the second byte of the gzip file signature, so BIS was sending a compressed body and the CSV decoder was reading it raw. The fix was one header, `Accept-Encoding: identity`. Expect a bug like this on every new API.

---

## 3. Anatomy of `source_oecd_sdmx.yaml`

Reading top to bottom:

```yaml
version: 7.49.0              # airbyte-cdk version the manifest targets
type: DeclarativeSource

check:                       # what `source.check()` does: read one stream to prove
  type: CheckStream          # the API is reachable and the config is valid
  stream_names: [h3_unemployment_rate]
```

### `definitions`: the reusable stream template

```yaml
definitions:
  oecd_stream:
    type: DeclarativeStream
    retriever:
      type: SimpleRetriever
      requester:                         # ① HOW to call the API
        type: HttpRequester
        url_base: https://sdmx.oecd.org/public/rest/data/
        path: >-
          {{ parameters['dataflow'] }}/{{ parameters['key_template'] | replace('{countries}', config['countries'] | join('+')) }}
        request_parameters:
          startPeriod: "{{ config['start_period'] }}"
          format: csv
        error_handler:                   # ② retries with exponential backoff on 429/5xx
          ...
      record_selector:                   # ③ WHERE the records are in the response
        extractor: {type: DpathExtractor, field_path: []}   # [] = every row
      decoder: {type: CsvDecoder}        # ④ response is CSV, so each row becomes a dict
      paginator: {type: NoPagination}    # SDMX returns everything in one response
    transformations:                     # ⑤ reshape each record
      - type: AddFields
        fields:
          - {path: [raw],      value: "{{ record }}"}          # keep the full source row
          - {path: [ref_area], value: "{{ record['REF_AREA'] }}"}
          ...
```

Notes on ①–⑤:

- **`{{ … }}` is Jinja.** Three variables are available:
  - `config`: what the user passes in, i.e. the countries and the start period from `pipeline/config.yaml`.
  - `parameters`: per-stream constants (see below).
  - `record`: the current row, available inside transformations.
- **The `path` line builds the URL.** `config['countries'] | join('+')` turns `[USA, CAN, …]` into `USA+CAN+…`, which is then put in place of `{countries}` in the stream's key template.
- **CSV over JSON.** SDMX-JSON stores observations as positional indexes that point into a separate dimension table, which is awkward to unpack in YAML. Requesting `format=csv` and using `CsvDecoder` gives one flat row per observation.
- **`AddFields`** gives every stream the same standard columns (`ref_area`, `time_period`, `obs_value`, …) even though the source CSVs have different columns. BIS calls the country column `BORROWERS_CTY`, and `area_column` handles that. The untouched row is kept in `raw`, so nothing the source published is lost.

### `streams`: one entry per indicator, built by reference

```yaml
streams:
  - $ref: "#/definitions/oecd_stream"     # inherit everything above
    name: k3_house_price_to_income
    $parameters:                          # ...and override only these
      indicator_id: K3
      dataflow: OECD.ECO.MPD,DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES,1.0
      key_template: "{countries}.Q.HPI_YDH.IX.S"
```

`$ref` copies a definition and `$parameters` feeds `parameters[...]`. Adding an indicator is therefore about five lines of YAML.

### `schemas` and `spec`

- `schemas.sdmx_observation` is the JSON Schema of the output record. PyAirbyte uses it to create the DuckDB columns. Values stay **strings** on purpose: bronze means "as published", and casting happens in dbt.
- `spec.connection_specification` is the form of config the connector accepts, with defaults. In the Airbyte UI it becomes the setup form.

---

## 4. How PyAirbyte runs it (`pipeline/ingest/run_ingest.py`)

```python
manifest = yaml.safe_load(open("source_oecd_sdmx.yaml"))
source = ab.get_source("source-oecd-sdmx",
                       config={"countries": [...], "start_period": "2009"},
                       source_manifest=manifest)   # no Docker, no registry: run this YAML
source.check()                    # runs the `check:` block
source.select_all_streams()
result = source.read(cache=cache, force_full_refresh=True)   # cache = local DuckDB
df = result["k3_house_price_to_income"].to_pandas()
```

After that, the runner:

1. writes each stream to `data/bronze/<stream>/vintage=<date>/data.parquet`, an immutable snapshot;
2. writes `data/bronze/_runs/<date>.json` with row counts and per-country coverage;
3. calls `load_bronze.py`, which rebuilds the `bronze.*` tables in `data/warehouse.duckdb` from **all** vintages.

Why full refresh instead of incremental: OECD and BIS revise past quarters. A full pull each run, kept as a dated vintage, is what makes robustness check R6 (vintage tracking) possible.

---

## 5. Exercise: add a new stream yourself

**Goal:** add BIS headline CPI for Japan as a backup deflator, since OECD's Japanese CPI stops in 2021Q2.

1. Find the dataflow: `curl -s https://stats.bis.org/api/v1/dataflow/BIS/all/latest | grep -i cpi` → `WS_LONG_CPI`.
2. Find the key: `curl "https://stats.bis.org/api/v1/data/WS_LONG_CPI/M.JP?startPeriod=2024&format=csv" | head`. Read the `UNIT_MEASURE` column (index level vs. % change) and decide which you want.
3. Add to `source_bis_sdmx.yaml`:
   ```yaml
     - $ref: "#/definitions/bis_stream"
       name: ref_headline_cpi_bis
       $parameters:
         indicator_id: CPI_BIS
         dataflow: WS_LONG_CPI
         area_column: REF_AREA
         key_template: "M.{countries}.628"   # 628 = index level (checked 2026-11-21: JP monthly data present)
   ```
4. Add the stream name to `EXPECTED` in `tests/test_manifests.py`, then run `uv run pytest`.
5. Run `uv run python pipeline/ingest/run_ingest.py --source bis`. The new table `bronze.ref_headline_cpi_bis` appears.
6. Add a one-line staging model `pipeline/transform/models/staging/stg_ref_headline_cpi_bis.sql` containing `{{ stg_sdmx('ref_headline_cpi_bis') }}`, add the source to `_sources.yml`, then run `dbt build`.

---

## 6. Using the Airbyte UI instead (optional)

In Airbyte Cloud or OSS, go to **Builder → Import a YAML** and choose either manifest. You get the same streams with a visual editor and a test button. You can then publish the connector to your workspace and schedule it to a destination such as S3, BigQuery or Postgres. Nothing in the YAML is specific to PyAirbyte.

---

## 7. The full local flow

```bash
uv sync                                                        # Python 3.12 + airbyte + dbt-duckdb
uv run python pipeline/ingest/run_ingest.py                    # APIs → Parquet vintages → bronze.* in DuckDB
uv run dbt build --project-dir pipeline/transform \
                 --profiles-dir pipeline/transform             # bronze → staging.* views + 61 tests
uv run duckdb data/warehouse.duckdb                            # explore (or: DBeaver / VS Code DuckDB extension)
```

```
OECD SDMX ─┐   Airbyte declarative     data/bronze/*.parquet        data/warehouse.duckdb
BIS SDMX  ─┴─▶ manifests (PyAirbyte) ─▶ (immutable vintages)  ─▶  bronze.*  ─dbt─▶ staging.* ─▶ silver/gold (next)
```
