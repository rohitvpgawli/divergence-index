# Data Sources & Availability Check

Status: bronze ingestion v0.1 · checked against the live APIs on **2026-11-21** · answers the "Data availability (Rohit)" open item in *Methodology v0.1 §11*.

No calculations are done at this stage. Bronze stores every series exactly as published.

## How ingestion works

| Piece | Where |
| --- | --- |
| Airbyte declarative (low-code) connector, OECD SDMX | `pipeline/ingest/airbyte/manifests/source_oecd_sdmx.yaml` |
| Airbyte declarative (low-code) connector, BIS SDMX | `pipeline/ingest/airbyte/manifests/source_bis_sdmx.yaml` |
| Runner (PyAirbyte, in-process, no Docker or Airbyte server) | `pipeline/ingest/run_ingest.py` |
| Cohort + start period | `pipeline/config.yaml` |
| Output | `data/bronze/<stream>/vintage=<date>/data.parquet` and `data/bronze/_runs/<date>.json` |

Every run is a full refresh from 2009 (a year before the window starts) and writes a new dated vintage. This preserves the history of OECD/BIS revisions for robustness check R6. The manifests are standard Airbyte YAML: they can be imported into the Airbyte Connector Builder (OSS or Cloud) without changes if we move to a hosted Airbyte later.

```bash
uv sync
uv run python pipeline/ingest/run_ingest.py
```

## Stream → indicator map

| Stream | Methodology use | Dataflow | Series key | SA? |
| --- | --- | --- | --- | --- |
| `h1_real_gdp_per_capita` | H1 | OECD `DF_QNA_EXPENDITURE_CAPITA` | `Q.Y.{c}.S1.S1.B1GQ_POP._Z._Z._Z.USD_PPP_PS.LR.LA.T0102` | Yes |
| `h2_share_price_index` | H2 (nominal) | OECD `DF_FINMARK` | `{c}.M.SHARE.IX._Z._Z._Z._Z.N` | n/a |
| `h3_unemployment_rate` | H3 | OECD `DF_IALFS_UNE_M` | `{c}.UNE_LF_M.PT_LF_SUB._Z.Y._T.Y_GE15._Z.M` | Yes |
| `k1_real_hh_disposable_income_pc` | K1 | OECD `DF_HHDASH_INDIC` | `Q.{c}.B6GS1M_R_POP.` | Yes |
| `k1_hh_disposable_income_nominal` | K4 denominator; K1 rebuild for KOR | OECD `DF_QSA` | `Q..{c}.S1M...B6G.......` | Mixed (below) |
| `ref_population` | per-capita divisor | OECD `DF_QNA_POP_EMPNC` | `Q..{c}..........` | Both |
| `ref_hh_consumption` | household consumption deflator | OECD `DF_QNA` | `Q..{c}...P31DC.......` | Both |
| `k2_household_dsr` | K2 | BIS `WS_DSR` | `Q.{c2}.H` | No (BIS publishes NSA) |
| `k3_house_price_to_income` | K3 | OECD `DF_HOUSE_PRICES` | `{c}.Q.HPI_YDH.IX.S` | Yes |
| `k4_cpi_components` | K4 numerator; H2 deflator (`_T`) | OECD `DF_PRICES_ALL` | `{c}..N.CPI.IX._T+CP01+CP045_0722.N._Z` | **No** |

`{c}` = `USA+CAN+GBR+DEU+AUS+JPN+KOR`; `{c2}` = BIS ISO-2 codes.

## Coverage (first → last period in the 2026-11-21 vintage)

| Stream | USA | CAN | GBR | DEU | AUS | JPN | KOR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H1 GDP/capita | →2026Q3 | →2026Q2 | →2026Q2 | →2026Q3 | →2026Q1 | →2026Q3 | →2025Q4 |
| H2 share prices (M) | →2026-10 | →2026-10 | →2026-10 | →2026-10 | →2026-10 | →2026-10 | →2026-10 |
| H3 unemployment (M) | →2026-10 | →2026-10 | →2026-08 | →2026-09 | →2026-10 | →2026-09 | →2026-10 |
| K1 real HDI/capita | →2026Q2 | →2026Q2 | →2026Q2 | →2026Q2 | →2026Q2 | **→2025Q1** | **not published** |
| K1 nominal HDI | →2026Q3 (SA) | →2026Q2 (SA) | →2026Q2 (SA) | →2026Q2 (SA) | →2026Q2 (SA) | **→2025Q1, NSA only** | **2010Q1→2024Q4, NSA only** |
| K2 DSR (BIS) | →2026Q1 | →2026Q1 | →2026Q1 | →2026Q1 | →2026Q1 | →2026Q1 | →2026Q1 |
| K3 price-to-income | →2026Q2 | →2026Q3 | →2026Q2 | →2026Q2 | →2026Q1 | →2025Q4 | →2026Q2 |
| K4 headline CPI | →2026Q3 | →2026Q3 | →2026Q3 | →2026Q3 | →2026Q3 | **→2021Q2** | →2026Q3 |
| K4 food CPI | ✓ | **→2025-05** | ✓ | ✓ | ✓ | **→2021Q2** | ✓ |
| K4 energy CPI | ✓ | **→2025-05** | ✓ | ✓ | **→2025Q2** | **→2021Q2** | ✓ |

All series start in 2009 except KOR nominal household income, which starts in exactly 2010Q1. That still covers all 40 reference quarters.

## Findings for the methodology open items

1. **BIS household DSR for all 7 from 2010: ✅ confirmed.** It is complete 2009Q1–2026Q1 for every country. It is published NSA only.
2. **Quarterly K1 for JPN and KOR: ⚠️ partial.**
   - **KOR** is absent from the OECD Household Dashboard (real HDI per capita). The inputs to rebuild it are available: nominal household income (QSA), population, and household consumption at current prices and in volume (deflator). The nominal income series is **NSA only and ends 2024Q4**.
   - **JPN** real and nominal household income both end at **2025Q1**, and nominal is NSA only.
3. **Licence-clean equity history from 2010: ⚠️ substitute in use.** `h2_share_price_index` is the OECD broad share-price index for each country. It is complete from 2009 for all 7 and OECD-licensed, but it is **not** the named benchmarks (S&P 500, TSX, FTSE 100, DAX, ASX 200, Nikkei 225, KOSPI). The named indices are proprietary (S&P DJI, FTSE Russell, STOXX, Nikkei, KRX), and free sources (Yahoo, Stooq) do not give a clean redistribution licence. Recommendation: keep OECD as H2 and cite the benchmarks only as context. This is a methodology decision for Juhi.
4. **Japan CPI gap (new).** OECD `DF_PRICES_ALL` holds Japanese CPI (headline, food, energy) only through **2021Q2**. This breaks both K4 and the H2 deflator for JPN. Candidate fixes: Statistics Bureau of Japan / e-Stat API (needs a free app ID) or the BIS consumer price series (headline only).
5. **Seasonal adjustment (open item §3).** NSA-only inputs: K2 (all countries), K4 food and energy CPI (all countries; OECD publishes no SA COICOP sub-indices), and nominal household income for JPN and KOR.
6. **Latest common quarter implication (§7).** As the data stand, KOR nominal income (2024Q4) and JPN CPI (2021Q2) would set the panel end date. Unless items 2 and 4 are resolved, the "shorten for all vs. drop for that country" rule (open item §11) has to be decided before any composite is computed.
