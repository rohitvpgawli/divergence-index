# Mock Gold — for dashboard build only

> **Every number in this folder is synthetic.** Do not quote, chart publicly, or sanity-check methodology against it.
> It exists so the dashboard can be built against the exact Gold schema before real Gold lands.

- **Schema source of truth:** [`docs/DATA_CONTRACT.md`](../../docs/DATA_CONTRACT.md) (v1.0.0-draft)
- **Schema version stamped here:** `1.0.0-mock` (in both JSON files and in the Parquet file metadata key `divergence.schema_version`)
- **Regenerate:** `uv run python pipeline/mock/make_mock_gold.py`

When real Gold ships, it goes to `data/gold/` with the same file names and columns. Switching should only mean changing the folder path.

## Files

| File | What it is |
|---|---|
| `divergence_panel.parquet` | Canonical panel: 469 rows (7 countries × 67 quarters, 2010-Q1 → 2026-Q3) × 41 columns |
| `divergence_panel.csv` | Same data as CSV |
| `component_contributions.json` | Per country → quarter: gap, sub-indices, additive contributions, guarded shares (2015-Q1 → 2026-Q2) |
| `pipeline_metadata.json` | Freshness and per-indicator metadata (labels, units, baseline mean/SD) |

## `divergence_panel` columns (in this exact order)

Key: (`country_iso`, `quarter`). Sorted by country, then quarter. Countries: `AUS, CAN, DEU, GBR, JPN, KOR, USA`.

**Keys and flags (7)**

| Column | Type | Notes |
|---|---|---|
| `country_iso` | string | ISO-3 |
| `quarter` | string | `YYYY-Qn` |
| `quarter_start_date` | date | Use this for x-axes |
| `is_baseline_window` | bool | 2010-Q1 → 2019-Q4 |
| `is_complete` | bool | All 7 components present |
| `is_composite_eligible` | bool | **Filter on this for headline charts and the leaderboard** |
| `n_components_available` | int | 0–7 |

**Components (21).** Each of the 7 stems below comes in `_raw`, `_z` and `_idx100` (e.g. `k2_hh_dsr_z`):

| ID | Stem | Higher raw value is… | `_z` / `_idx100` |
|---|---|---|---|
| H1 | `h1_real_gdp_pc` | good | as-is |
| H2 | `h2_real_equity` | good | as-is |
| H3 | `h3_unemployment` | bad | inverted |
| K1 | `k1_real_hhdi_pc` | good | as-is |
| K2 | `k2_hh_dsr` | bad | inverted |
| K3 | `k3_house_price_income` | bad | inverted |
| K4 | `k4_essentials_cpi` | bad | inverted |

- `_z` and `_idx100`: **higher = better** for every indicator. Compare these across countries.
- `_raw`: native units and direction. **Not comparable across countries.** Use only for single-country deep dives.

**Composites (6):** `headline_z`, `kitchen_table_z`, `divergence_gap_z`, `headline_idx100`, `kitchen_table_idx100`, `divergence_gap_idx100`. A composite is null if any of its components is null.

**Contributions (7):** `contrib_h1_z` … `contrib_k4_z`. On eligible rows they add up exactly to `divergence_gap_z`. A positive K contribution means that household measure is worse than its baseline, so it widens the gap. This is the data for the waterfall view.

## Edge cases the mock includes on purpose

- **2026-Q3 is a "leading" quarter.** H1, H2, H3 and K4 have values, but K1, K2 and K3 are null. So `is_composite_eligible = false` and all composites are null. The UI should label it as a leading indicator, or leave it out.
- **Suppressed shares.** In `component_contributions.json`, when `|divergence_gap_z| < 0.25`, `shares` is `null` and `shares_suppressed` is `true`. In that case show additive contributions, not percentages.
- **Real nulls only.** Missing values are empty CSV cells or Parquet nulls, never 0 or "NA".

## What the mock does *not* include yet

- Any `baseline_window_override` entries. With real data, some may be non-empty (for example KOR K2) and need a disclosure.
- Countries whose `latest_complete_quarter` differs. Here all are 2026-Q2.
- `revision_alerts` and `warnings` are empty arrays. Render the empty state.
