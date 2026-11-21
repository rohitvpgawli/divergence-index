# DATA_CONTRACT.md — Gold Layer Schema Guarantees

**Contract version:** 1.0.0-draft
**Status:** DRAFT — for Milestone 1 (Data Contract Lock) review
**Producer:** Engineering track (`/pipeline/`) — Rohit
**Consumer:** L&E / Visualization track (`/analysis/`, `/app/`) — Juhi
**Scope:** Everything under `/data/gold/`. Bronze and Silver are internal to Engineering and carry no guarantees.

---

## 0. Purpose & Rules of Engagement

1. `/data/gold/` is the only interface between the two tracks. L&E never reads Bronze/Silver; Engineering never edits `/analysis/` or `/app/`.
2. Anything not written in this document is not guaranteed. If L&E needs it, it gets added here first, then built.
3. Any change to file names, column names, data types, units, polarity, or key structure is a **breaking change** (see §8).
4. If a guarantee can't be met on a given run, the pipeline **fails loudly and does not overwrite Gold**. The last good Gold stays published (see §7).

---

## 1. Files Guaranteed

| File | Format | Grain | Primary consumer |
| :--- | :--- | :--- | :--- |
| `divergence_panel.parquet` | Parquet (canonical) | 1 row per `country_iso` × `quarter` | Notebooks, robustness checks |
| `divergence_panel.csv` | CSV, UTF-8, comma, header row | Identical to Parquet | Spreadsheet review, LinkedIn chart exports |
| `component_contributions.json` | JSON | Nested: country → quarter → components | Decomposition / waterfall visual |
| `pipeline_metadata.json` | JSON | 1 object per run | Dashboard freshness banner, methodology drawer |

**The Parquet file is canonical.** The CSV is a byte-for-byte derivative of the same DataFrame. Any disagreement between them is a bug.

---

## 2. Global Conventions

| Convention | Rule |
| :--- | :--- |
| Country key | `country_iso` — ISO 3166-1 alpha-3, uppercase. Allowed set: `USA, CAN, GBR, DEU, AUS, JPN, KOR`. No other values ever. |
| Time key | `quarter` — string `YYYY-Qn` (e.g. `2019-Q4`). Also provided: `quarter_start_date` (ISO date, first day of quarter) for plotting. |
| Primary key | (`country_iso`, `quarter`) — unique, non-null. |
| Panel coverage | Balanced panel from `2010-Q1` through `latest_published_quarter` for all 7 countries. Rows exist even when values are null; there are no missing rows. |
| Sort order | `country_iso` ASC, then `quarter` ASC. |
| Nulls | Real nulls only (Parquet null / empty CSV cell). Never `0`, `-999`, `"NA"` or `"n/a"` as placeholders. |
| Numeric type | `float64`. No rounding in Parquet. CSV is written with full precision (no fixed decimal truncation). |
| Polarity | All `_z` and `_idx100` columns are **polarity-adjusted: higher = better for households/economy**. All `_raw` columns are in **native units and native direction** (not inverted). |
| Seasonality | All quarterly values are seasonally adjusted where the source provides SA; where it doesn't, see `sa_status` in metadata (§6). |
| Naming | `snake_case`, lowercase. Component columns follow `{id}_{short_name}_{form}`. |

---

## 3. `divergence_panel` — Column Specification

### 3.1 Keys & Flags

| Column | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `country_iso` | string | No | ISO-3 code. |
| `quarter` | string | No | `YYYY-Qn`. |
| `quarter_start_date` | date | No | First calendar day of the quarter. |
| `is_baseline_window` | bool | No | `True` for 2010-Q1 → 2019-Q4 (Z-score estimation window). |
| `is_complete` | bool | No | `True` only if all 7 components are non-null for this row. |
| `is_composite_eligible` | bool | No | `True` if `quarter ≤ latest_complete_common_quarter` **and** `is_complete`. Headline charts and the leaderboard filter on this. |
| `n_components_available` | int | No | 0–7. Count of non-null raw components in this row. |

### 3.2 Component Columns (7 indicators × 3 forms = 21 columns)

Every indicator ships in three forms:

- `_raw` — native units, native direction, post-deflation and post-frequency-alignment (Silver output).
- `_z` — Model 1. Polarity-signed Z-score against the country's own 2010-Q1–2019-Q4 mean/SD.
- `_idx100` — Model 2. Rebased so `2019-Q4 = 100`. Inverted indicators use `200 − (x / x₂₀₁₉Q₄ × 100)`.

| ID | Column stem | `_raw` unit | Polarity sign `s_k` | Inverted in `_z` / `_idx100`? |
| :--- | :--- | :--- | :--- | :--- |
| H1 | `h1_real_gdp_pc` | Chained-volume national currency per person, SA | +1 | No |
| H2 | `h2_real_equity` | Quarterly avg. of index level ÷ headline CPI × 100 | +1 | No |
| H3 | `h3_unemployment` | % of labour force, SA, quarterly avg. | −1 | Yes |
| K1 | `k1_real_hhdi_pc` | Real household disposable income per person, national currency, SA | +1 | No |
| K2 | `k2_hh_dsr` | % of household disposable income | −1 | Yes |
| K3 | `k3_house_price_income` | OECD standardised ratio index (source base year — see metadata) | −1 | Yes |
| K4 | `k4_essentials_cpi` | Cumulative price-level index, food + energy (source base year — see metadata) | −1 | Yes |

So, for example: `k2_hh_dsr_raw`, `k2_hh_dsr_z`, `k2_hh_dsr_idx100`.

**Note on `_raw` comparability:** `_raw` values are **not comparable across countries** (different currencies, base years, and DSR definitions). They exist for auditability and country deep-dives only. Cross-country visuals use `_z` or `_idx100`.

### 3.3 Composite Columns

| Column | Formula | Nullable when |
| :--- | :--- | :--- |
| `headline_z` | mean(`h1_z`, `h2_z`, `h3_z`) | Any H component null |
| `kitchen_table_z` | mean(`k1_z`, `k2_z`, `k3_z`, `k4_z`) | Any K component null |
| `divergence_gap_z` | `headline_z − kitchen_table_z` | Either sub-index null |
| `headline_idx100` | mean(`h1_idx100`, `h2_idx100`, `h3_idx100`) | Any H component null |
| `kitchen_table_idx100` | mean(`k1_idx100` … `k4_idx100`) | Any K component null |
| `divergence_gap_idx100` | `headline_idx100 − kitchen_table_idx100` (index points) | Either sub-index null |

**No partial composites.** If any component is null, the composite is null. The pipeline does not re-weight over the available components. (Leave-one-out variants live in `/analysis/robustness/` and are out of scope for this contract.)

### 3.4 Additive Contribution Columns (7 columns)

| Column | Formula |
| :--- | :--- |
| `contrib_h1_z`, `contrib_h2_z`, `contrib_h3_z` | `(1/3) · h{k}_z` |
| `contrib_k1_z` … `contrib_k4_z` | `−(1/4) · k{k}_z` |

**Identity guarantee:** `sum(contrib_*_z) == divergence_gap_z` (tolerance 1e-9) on every composite-eligible row.

> **Why this departs from the methodology doc:** METHODOLOGY §6 Step 3 defines contribution as a *share*, `C = w·z / Δ`. Shares blow up as Δ approaches 0 and flip sign when Δ crosses zero, so a quarter with Δ = 0.02 would show components "contributing" ±2,000%. The contract therefore ships **additive contributions in Z-units**, which always stack exactly to Δ. Shares, where they are still wanted, are derived in `component_contributions.json` with a guard (§4).
>
> **Sign convention:** K components enter Δ negatively. A *positive* `contrib_k2_z` means "DSR is worse than its baseline, so it widens the gap". A worse Kitchen Table always pushes Δ up.

### 3.5 Column Count

**7 key/flag columns + 21 component columns + 6 composite columns + 7 contribution columns = 41 columns**, in exactly that order. Column order is part of the contract.

---

## 4. `component_contributions.json` — Structure

Pre-aggregated for the "Anatomy of the Squeeze" and leaderboard views. Composite-eligible rows only.

```json
{
  "schema_version": "1.0.0",
  "model": "z",
  "latest_complete_common_quarter": "2026-Q2",
  "components": [
    {"id": "H1", "label": "Real GDP per capita", "basket": "headline", "weight": 0.3333, "sign_in_gap": 1},
    {"id": "K2", "label": "Household debt service ratio", "basket": "kitchen_table", "weight": 0.25, "sign_in_gap": -1}
  ],
  "countries": {
    "AUS": {
      "2026-Q2": {
        "divergence_gap_z": 1.42,
        "headline_z": 0.61,
        "kitchen_table_z": -0.81,
        "contributions": {"H1": 0.10, "H2": 0.31, "H3": 0.20, "K1": 0.05, "K2": 0.44, "K3": 0.21, "K4": 0.11},
        "shares": {"H1": 0.070, "H2": 0.218, "H3": 0.141, "K1": 0.035, "K2": 0.310, "K3": 0.148, "K4": 0.077},
        "shares_suppressed": false
      }
    }
  }
}
```
*(Numbers above are illustrative placeholders, not results.)*

**Guarantees:**
- `contributions` values sum to `divergence_gap_z` (tolerance 1e-9).
- `shares = contributions / divergence_gap_z`, emitted **only when `|divergence_gap_z| ≥ 0.25`**. Below that threshold `shares` is `null` and `shares_suppressed` is `true`. The UI must then show additive contributions, not percentages.
- Every quarter from `2015-Q1` (the hero-view start) through `latest_complete_common_quarter` is present for each country, unless the row is not composite-eligible.

---

## 5. Temporal Guarantees

| Term | Definition |
| :--- | :--- |
| `latest_published_quarter` | Latest quarter with **any** non-null component for **any** country. The panel extends to here. |
| `latest_complete_quarter[country]` | Latest quarter where that country has all 7 components. |
| `latest_complete_common_quarter` | `min(latest_complete_quarter)` across all 7 countries. **The leaderboard and the "current Δ" figure are stated as of this quarter only.** |

Monthly-sourced series (H2, H3, K4) can run 1–2 quarters ahead of K1 and K2. Those fresher values appear in `_raw`/`_z`/`_idx100` columns but are **not** composite-eligible. The dashboard may display them as clearly labelled "leading indicators".

**Partial quarters:** A monthly-sourced quarter is only populated once all 3 months are available. No 1- or 2-month averages.

---

## 6. `pipeline_metadata.json` — Structure

```json
{
  "schema_version": "1.0.0",
  "run_id": "2026-11-15T06:00:00Z_a1b2c3d",
  "run_timestamp_utc": "2026-11-15T06:04:12Z",
  "git_commit": "a1b2c3d",
  "run_status": "success",
  "latest_published_quarter": "2026-Q3",
  "latest_complete_common_quarter": "2026-Q2",
  "latest_complete_quarter_by_country": {"USA": "2026-Q2", "CAN": "2026-Q2"},
  "baseline": {"z_window": ["2010-Q1", "2019-Q4"], "idx100_anchor": "2019-Q4"},
  "indicators": {
    "K2": {
      "label": "Household debt service ratio",
      "source": "BIS",
      "dataset": "WS_DSR",
      "series_keys": {"AUS": "Q.AU.H"},
      "native_frequency": "Q",
      "unit": "% of household disposable income",
      "sa_status": {"AUS": "SA"},
      "source_base_year": null,
      "vintage_date": {"AUS": "2026-09-08"},
      "z_baseline_stats": {"AUS": {"mean": 0.0, "sd": 0.0, "n_quarters": 40}},
      "baseline_window_override": {}
    }
  },
  "validation": {
    "checks_run": 0,
    "checks_failed": 0,
    "warnings": [],
    "revision_alerts": []
  }
}
```
*(Values are illustrative.)*

**Why each field matters to L&E:**
- `z_baseline_stats` lets the methodology drawer show readers exactly what "1 standard deviation" means for each country (e.g. "for Australia, 1σ of DSR ≈ X percentage points").
- `baseline_window_override` records any country/indicator whose series starts after 2010-Q1. Any non-empty entry must be disclosed in that country's brief.
- `revision_alerts` lists any value revised by more than ±2σ since the previous run (country, quarter, indicator, old value, new value). These feed the "Quarterly Divergence Pulse" caveats.
- `series_keys` + `vintage_date` make every number traceable to an exact source pull.

---

## 7. Quality Guarantees (enforced by `/pipeline/validate/`)

The run **fails and Gold is not overwritten** if any of these fail:

| # | Check | Applies to |
| :--- | :--- | :--- |
| Q1 | Schema matches §3 exactly (names, order, dtypes) — pandera | `divergence_panel` |
| Q2 | Primary key unique and non-null; balanced panel (7 × N quarters) | `divergence_panel` |
| Q3 | Zero nulls in any component for 2010-Q1 → `latest_complete_common_quarter`, except entries declared in `baseline_window_override` | `divergence_panel` |
| Q4 | Every `*_idx100` equals 100.0 at 2019-Q4 (tolerance 1e-9) | `divergence_panel` |
| Q5 | Every `*_z` over the baseline window has mean ≈ 0 (\|μ\| < 1e-6) and SD ≈ 1 (\|σ − 1\| < 1e-6) per country, using the **same ddof as in transform (ddof = 1)** | `divergence_panel` |
| Q6 | Contribution identity holds (§3.4, §4) | both |
| Q7 | Polarity sanity: corr(`k2_hh_dsr_raw`, `k2_hh_dsr_z`) < 0, and the same for H3, K3, K4; > 0 for H1, H2, K1 | `divergence_panel` |
| Q8 | Parquet and CSV are identical when reloaded | both panel files |
| Q9 | JSON validates against a checked-in JSON Schema (`/docs/schemas/*.schema.json`) | both JSON files |

**Warnings (logged, run continues):** any single-quarter revision greater than ±2σ (→ `revision_alerts`); `latest_complete_common_quarter` not advancing for more than 2 consecutive runs; any `|z| > 6`.

---

## 8. Versioning & Change Management

- `schema_version` follows semver and appears in both JSON files. The Parquet file carries the same value as file-level metadata (`divergence.schema_version`).
- **MAJOR** — rename/remove a column, change a dtype/unit/polarity/formula, change the baseline window or anchor quarter. Requires a PR approved by **both** owners and an entry in `CHANGELOG` under `/docs/`.
- **MINOR** — add a column at the end or a JSON field. One approval; consumers must tolerate it.
- **PATCH** — data refresh, source revision, bug fix that doesn't change the schema.
- Gold is committed per run, so `git log data/gold/` is the vintage history. Retrospective OECD/BIS revisions therefore stay auditable without a separate snapshot store.

---

## 9. Explicitly NOT Guaranteed in v1

- PCA-weighted composites, leave-one-out variants (→ `/analysis/robustness/`, L&E-owned).
- Median (vs. mean) household measures.
- Adjusted disposable income incl. social transfers in kind (cited qualitatively per METHODOLOGY §7).
- Monthly-frequency outputs.
- Countries outside the 7-country cohort.

---

## 10. Open Decisions — Resolve Before Lock

| # | Issue | Recommended default | Owner |
| :--- | :--- | :--- | :--- |
| D1 | The methodology doc calls the panel "long-format" but lists wide indicator columns. | **Panel = one row per country-quarter (wide on indicators), as specified here.** If a tidy long table is wanted for plotting libraries, add `components_long.parquet` as a v1.1 MINOR addition. | Both |
| D2 | K4 "Food + Energy" is two OECD COICOP series. How are they combined? | Use national CPI basket weights for food and energy, re-normalised. Fallback: OECD's own "food and energy" aggregate if one exists for all 7. Record the method in `indicators.K4`. | Rohit to confirm availability |
| D3 | Source coverage of the full 2010-Q1 baseline is unverified — especially quarterly K1 for JPN/KOR, and K2 for KOR. | Confirm during ingestion. Any gap → `baseline_window_override` + disclosure, not silent imputation. | Rohit |
| D4 | Population denominator for H1/K1 per-capita | One consistent OECD quarterly population series for both H1 and K1, recorded in metadata. | Rohit |
| D5 | Equity data source & licensing (Nikkei 225, KOSPI, ASX 200 redistribution terms) | Publish only the derived `h2_real_equity_z`/`_idx100` if raw redistribution is restricted. `_raw` may then be null by design — declare it in metadata. | Rohit |
| D6 | Share-suppression threshold (§4) | 0.25σ. Revisit after first real data. | Juhi |
| D7 | Which CPI deflates H2 (headline CPI) vs K1 (household consumption deflator) | Keep as specified in the methodology doc. Log the exact series keys. | Rohit |

---

## 11. Milestone 1 Acceptance Checklist

- [ ] D1–D7 resolved and this doc bumped to `1.0.0`
- [ ] `divergence_panel.parquet` + `.csv` delivered and passing Q1–Q9
- [ ] `component_contributions.json` + `pipeline_metadata.json` validate against checked-in JSON Schemas
- [ ] Sanity review on all 7 countries: L&E plots `headline_z` vs `kitchen_table_z` and signs off that the directions match known episodes (e.g. 2020-Q2 GDP collapse; 2022–23 DSR rise in CAN/AUS)
- [ ] Both owners approve the PR adding this file
