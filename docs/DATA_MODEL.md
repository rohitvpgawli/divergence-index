# Data model: lineage & ERD

How the tables connect, from Airbyte's raw files in S3 to the gold panel Juhi's dashboard reads.
The lineage below is **generated from dbt's own dependency graph** (`target/manifest.json`), so it matches the code.
For the interactive version (click any model to see its SQL, columns and tests):

```bash
uv run dbt docs generate --project-dir pipeline/transform --profiles-dir pipeline/transform
uv run dbt docs serve --project-dir pipeline/transform --profiles-dir pipeline/transform   # opens http://localhost:8080
```

## 1. Lineage (model-level)

Read left to right. Each staging box also stands for its bronze table in S3
(`s3://…/airbyte/<bis|oecd>/<stream>/`). That step is always one-to-one, so it's folded in.

```mermaid
flowchart LR
  subgraph S3["S3 bronze · Airbyte (1 table per stream)"]
    direction TB
    subgraph BIS["bis/"]
      stg_k2_household_dsr["stg_k2_household_dsr"]
      stg_ref_headline_cpi_bis["stg_ref_headline_cpi_bis"]
    end
    subgraph OECD["oecd/"]
      stg_h1_real_gdp_per_capita["stg_h1_real_gdp_per_capita"]
      stg_h2_share_price_index["stg_h2_share_price_index"]
      stg_h3_unemployment_rate["stg_h3_unemployment_rate"]
      stg_k1_hh_disposable_income_nominal["stg_k1_hh_disposable_income_nominal"]
      stg_k1_real_hh_disposable_income_pc["stg_k1_real_hh_disposable_income_pc"]
      stg_k3_house_price_to_income["stg_k3_house_price_to_income"]
      stg_k4_cpi_components["stg_k4_cpi_components"]
      stg_ref_cpi_weights["stg_ref_cpi_weights"]
      stg_ref_gdp_volume["stg_ref_gdp_volume"]
      stg_ref_hh_consumption["stg_ref_hh_consumption"]
      stg_ref_population["stg_ref_population"]
    end
  end
  subgraph SEED["seeds (reference)"]
    countries[("countries")]
    dim_indicator[("dim_indicator")]
  end
  subgraph SLV["silver: one correct value per country × quarter"]
    slv_h1_real_gdp_pc["slv_h1_real_gdp_pc"]
    slv_h2_real_equity["slv_h2_real_equity"]
    slv_h3_unemployment["slv_h3_unemployment"]
    slv_hh_consumption_deflator["slv_hh_consumption_deflator"]
    slv_hh_income_nominal["slv_hh_income_nominal"]
    slv_indicator_quarterly["slv_indicator_quarterly"]
    slv_k1_real_hhdi_pc["slv_k1_real_hhdi_pc"]
    slv_k2_hh_dsr["slv_k2_hh_dsr"]
    slv_k3_house_price_income["slv_k3_house_price_income"]
    slv_k4_essentials["slv_k4_essentials"]
    slv_population["slv_population"]
    slv_quarter_spine["slv_quarter_spine"]
  end
  subgraph GLD["gold: scores & contract panel"]
    gld_baseline_stats["gld_baseline_stats"]
    gld_divergence_panel["gld_divergence_panel"]
    gld_indicator_scores["gld_indicator_scores"]
  end
  EXPORT[["export_gold.py → data/gold/<br/>divergence_panel.parquet/.csv<br/>component_contributions.json<br/>pipeline_metadata.json"]]
  countries --> slv_h2_real_equity
  countries --> slv_k2_hh_dsr
  countries --> slv_quarter_spine
  dim_indicator --> gld_baseline_stats
  dim_indicator --> gld_indicator_scores
  gld_baseline_stats --> gld_indicator_scores
  gld_indicator_scores --> gld_divergence_panel
  slv_h1_real_gdp_pc --> slv_indicator_quarterly
  slv_h2_real_equity --> slv_indicator_quarterly
  slv_h3_unemployment --> slv_indicator_quarterly
  slv_hh_consumption_deflator --> slv_k1_real_hhdi_pc
  slv_hh_income_nominal --> slv_k1_real_hhdi_pc
  slv_hh_income_nominal --> slv_k4_essentials
  slv_indicator_quarterly --> gld_baseline_stats
  slv_indicator_quarterly --> gld_indicator_scores
  slv_indicator_quarterly --> slv_quarter_spine
  slv_k1_real_hhdi_pc --> slv_indicator_quarterly
  slv_k2_hh_dsr --> slv_indicator_quarterly
  slv_k3_house_price_income --> slv_indicator_quarterly
  slv_k4_essentials --> slv_indicator_quarterly
  slv_population --> slv_h1_real_gdp_pc
  slv_population --> slv_k1_real_hhdi_pc
  slv_population --> slv_k4_essentials
  slv_quarter_spine --> gld_indicator_scores
  stg_h2_share_price_index --> slv_h2_real_equity
  stg_h3_unemployment_rate --> slv_h3_unemployment
  stg_k1_hh_disposable_income_nominal --> slv_hh_income_nominal
  stg_k2_household_dsr --> slv_k2_hh_dsr
  stg_k3_house_price_to_income --> slv_k3_house_price_income
  stg_k4_cpi_components --> slv_k4_essentials
  stg_ref_cpi_weights --> slv_k4_essentials
  stg_ref_gdp_volume --> slv_h1_real_gdp_pc
  stg_ref_headline_cpi_bis --> slv_h2_real_equity
  stg_ref_hh_consumption --> slv_hh_consumption_deflator
  stg_ref_population --> slv_population
  gld_divergence_panel --> EXPORT
  gld_baseline_stats -.-> EXPORT
  gld_indicator_scores -.-> EXPORT
  DASH([Juhi's dashboard]):::dash
  EXPORT --> DASH
  classDef dash fill:#fde68a,stroke:#b45309,color:#000
```

## 2. Which inputs build each indicator (silver detail)

```mermaid
flowchart LR
    subgraph shared["shared silver inputs"]
        POP[slv_population]
        INC[slv_hh_income_nominal]
        DEF[slv_hh_consumption_deflator]
    end
    GDP[stg_ref_gdp_volume] --> H1[slv_h1_real_gdp_pc]
    POP --> H1
    SH[stg_h2_share_price_index] --> H2[slv_h2_real_equity]
    CPIB[stg_ref_headline_cpi_bis] --> H2
    UNE[stg_h3_unemployment_rate] --> H3[slv_h3_unemployment]
    INC --> K1[slv_k1_real_hhdi_pc]
    DEF --> K1
    POP --> K1
    DSR[stg_k2_household_dsr] --> K2[slv_k2_hh_dsr]
    HPI[stg_k3_house_price_to_income] --> K3[slv_k3_house_price_income]
    CPI[stg_k4_cpi_components] --> K4[slv_k4_essentials]
    W[stg_ref_cpi_weights] --> K4
    INC --> K4
    POP --> K4
```

| Indicator | Built from | Key rule |
| --- | --- | --- |
| H1 real GDP per capita | GDP chain-linked volume (T0102, SA) ÷ population | Same population series as K1 and K4 (D4) |
| H2 real equity | quarterly avg. share index ÷ quarterly avg. BIS headline CPI × 100 | Complete quarters only (3 months) |
| H3 unemployment | quarterly avg. of monthly rate | Complete quarters only |
| K1 real household income per capita | nominal income ÷ household consumption deflator ÷ population | Built the same way for all 7 (KOR not in OECD dashboard) |
| K2 debt service ratio | BIS as published | NSA |
| K3 house price-to-income | OECD index as published | SA |
| K4 essentials burden | food & energy CPI (fixed 2015–19 weights) ÷ nominal income per capita | `var('k4_definition')` switches to price level |

## 3. Entity-relationship diagram (silver & gold)

`PK` marks the columns that together identify a row. Every grain is enforced by a dbt uniqueness test.

```mermaid
erDiagram
    countries ||--o{ slv_quarter_spine : "iso3 = country_iso"
    countries ||--o{ slv_indicator_quarterly : "iso3 = country_iso"
    dim_indicator ||--o{ slv_indicator_quarterly : "indicator_id"
    dim_indicator ||--o{ gld_baseline_stats : "indicator_id"
    dim_indicator ||--o{ gld_indicator_scores : "indicator_id"
    slv_quarter_spine ||--|{ gld_indicator_scores : "country_iso + quarter_start_date (x 7 indicators)"
    slv_indicator_quarterly |o--o| gld_indicator_scores : "country_iso + quarter_start_date + indicator_id"
    gld_baseline_stats ||--o{ gld_indicator_scores : "country_iso + indicator_id"
    slv_quarter_spine ||--|| gld_divergence_panel : "country_iso + quarter (pivot of 7 score rows)"
    gld_indicator_scores }|--|| gld_divergence_panel : "7 rows -> 1 wide row"

    countries {
        varchar iso3 PK
        varchar iso2
        varchar country_name
        varchar archetype
    }
    dim_indicator {
        varchar indicator_id PK "H1..K4"
        int ordinal
        varchar basket "headline | kitchen_table"
        varchar column_stem "e.g. k2_hh_dsr"
        int polarity "+1 / -1"
        int sign_in_gap "+1 H / -1 K"
        varchar treatment "detrended | level"
        varchar unit
    }
    slv_quarter_spine {
        varchar country_iso PK
        date quarter_start_date PK
        varchar quarter "YYYY-Qn"
    }
    slv_indicator_quarterly {
        varchar country_iso PK
        date quarter_start_date PK
        varchar indicator_id PK
        varchar quarter
        double value "native units (= *_raw)"
        varchar sa_status
        varchar source_series
        date vintage
    }
    gld_baseline_stats {
        varchar country_iso PK
        varchar indicator_id PK
        varchar treatment
        int n_quarters "40"
        double mean "level only"
        double trend_alpha "detrended only"
        double trend_beta "detrended only"
        double sigma
    }
    gld_indicator_scores {
        varchar country_iso PK
        date quarter_start_date PK
        varchar indicator_id PK
        double raw
        double z
        double idx100
        double contrib_z
    }
    gld_divergence_panel {
        varchar country_iso PK
        varchar quarter PK
        date quarter_start_date
        boolean is_composite_eligible
        int n_components_available
        double h1_real_gdp_pc_raw_z_idx100 "x 7 indicators = 21 cols"
        double headline_z
        double kitchen_table_z
        double divergence_gap_z
        double contrib_h1_z_to_k4_z "7 cols"
    }
```

## 4. Grain of every layer

| Layer | Table(s) | One row per… | Shape |
| --- | --- | --- | --- |
| Bronze (S3) | 13 Airbyte streams | source observation × sync | as published, all syncs kept |
| Staging | `stg_*` (13) | source series × period, **latest sync only** | typed, labelled |
| Silver | `slv_<indicator>` (7) + 3 shared inputs | country × quarter | one clean value |
| Silver | `slv_indicator_quarterly` | country × quarter × indicator | **long** fact |
| Silver | `slv_quarter_spine` | country × quarter, 2010-Q1 → latest | balanced skeleton |
| Gold | `gld_baseline_stats` | country × indicator | 2010–19 μ/σ or trend α/β/σₑ |
| Gold | `gld_indicator_scores` | country × quarter × indicator | long: raw, z, idx100, contribution |
| Gold | `gld_divergence_panel` | country × quarter | **wide** One Big Table (38 cols, contract order) |

**Modeling techniques:** medallion layers; config-driven dimensions (`dim_indicator` drives polarity, weights and treatment);
a tidy long fact so the scoring maths is written once; a date spine for a balanced panel; and a wide One Big Table at the end
for the dashboard.
