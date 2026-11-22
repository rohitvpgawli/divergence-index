# Data Contract v1.0.0-draft — Engineering Review

**From:** Rohit (Engineering) · **To:** Juhi (L&E) · **Date:** 2026-11-21
**Re:** `docs/DATA_CONTRACT.md` §10 open decisions D2–D7, and the two deliberate changes from the methodology.
Every answer below comes from checking the live OECD/BIS APIs on 2026-11-21. Nothing has been computed yet. Full coverage tables are in `docs/DATA_SOURCES.md`.

---

## TL;DR

| # | Decision | Answer |
| --- | --- | --- |
| D2 | Combining Food + Energy CPI | ✅ **Confirm, with a fixed-weight variant.** OECD has no combined food & energy index, but it does publish national CPI basket weights for all 7. Year-by-year weights have gaps (CAN only from 2014, JPN only to 2019, USA only to 2022), so use **one fixed weight pair per country: the 2015–2019 average**. ⚠️ JPN food and energy CPI end at 2021-Q2 in OECD, so a second source is needed for Japan. |
| D3 | JPN/KOR income, KOR DSR back to 2010-Q1 | ✅ **All three cover the full 2010–19 baseline, so no `baseline_window_override` is needed.** ⚠️ The **ends** are the problem: KOR income stops at **2024-Q4** and JPN at **2025-Q1**. KOR has no published real series, and JPN/KOR nominal income is not seasonally adjusted. |
| D4 | Population denominator | ✅ **Confirm.** Use one OECD quarterly population series (`DF_QNA_POP_EMPNC`, POP, SA) for both H1 and K1. To make this possible, H1 should be **rebuilt as GDP volume ÷ that population**, rather than taken as OECD's ready-made per-capita series. This also gives the national-currency unit the contract asks for. |
| D5 | Equity source & licence | 🔁 **Change the default.** Use the **OECD national share price index** (`DF_FINMARK`), which is complete for all 7 from 2009 and published under OECD's open data terms. That means `h2_real_equity_raw` **can be published** and does not need to be null by design. The named benchmarks (S&P 500, Nikkei 225, …) are licensed products, so cite them as context only. |
| D7 | Deflators | ✅ **Confirm, with one source change.** For H2, deflate by **BIS headline CPI (`WS_LONG_CPI`, index)** for all 7, because OECD's Japanese CPI stops at 2021-Q2. For K1, use the household consumption deflator (current-price ÷ volume household consumption, OECD QNA), applied the same way for all 7. |

**Biggest consequence:** with today's data, `latest_complete_common_quarter` would be **2024-Q4**, held back by Korean household income. Section 3 lists the options.

---

## 1. Decisions in detail

### D2 — Food + Energy CPI

**What exists**
- OECD `DF_PRICES_ALL` holds food (`CP01`), energy (`CP045_0722`) and headline (`_T`) CPI as separate indices. There is **no combined "food and energy" index**. The closest is `_TXCP01_NRG`, all items *excluding* food and energy.
- OECD `DF_PRICES_N_IT_W` holds national CPI basket weights (per mille, annual) for `CP01`, `CP045_0722` and `_T`, for all 7 countries. Coverage:

  | Country | Weight years available |
  | --- | --- |
  | AUS | 2009–2024 |
  | CAN | 2014–2024 |
  | DEU | 2009–2025 |
  | GBR | 2009–2025 |
  | JPN | 2009–2019 |
  | KOR | 2009–2025 |
  | USA | 2009–2022 |

**Proposed rule (to write into `indicators.K4`)**
1. Rebase food and energy CPI to 2015 = 100.
2. For each country, compute a fixed weight pair from the average 2015–2019 basket weights: w_food = W_CP01 ÷ (W_CP01 + W_energy), w_energy = 1 − w_food. All 7 countries have weights for this window.
3. Combined food & energy index = w_food · food + w_energy · energy.

**Why fixed weights rather than chain-linking:**
- It's reproducible.
- It avoids patching the CAN, JPN and USA weight gaps.
- The weights sit inside the baseline window, so later basket changes don't move the baseline.

The trade-off is that recent basket shifts are ignored. I think that's acceptable because the baseline is 2010–19, but it's your call.

**Data problems**

| Gap | Effect on K4 | Option |
| --- | --- | --- |
| JPN: OECD food, energy and headline CPI all **end at 2021-Q2** | JPN K4 can't be built past 2021-Q2 | Statistics Bureau of Japan / e-Stat API (free app ID needed). BIS has headline CPI only, so it doesn't fix food & energy. |
| CAN: food and energy end at **2025-05** | CAN K4 runs only to 2025-Q1 | Statistics Canada's open API (table 18-10-0004), no key needed |
| AUS: energy ends at **2025-Q2** | AUS K4 runs only to 2025-Q2 | ABS Data API, no key needed |

All CPI components are **non-seasonally-adjusted** for every country; OECD doesn't publish adjusted food and energy indices. This should go into `sa_status` as "NSA", plus the open methodology item on how to seasonally adjust them.

**⚠️ Mismatch with the methodology:** Methodology v0.1 (§2, §3.4) redefined K4 as **food & energy CPI ÷ nominal household disposable income per capita**. The contract (§3.2) still describes K4 as the "cumulative price-level index, food + energy". The two need to agree before lock (see §2b below). If the methodology version wins, K4 inherits K1's coverage problems (D3).

### D3 — Baseline coverage for JPN/KOR household income and KOR DSR

| Series | Start | End | Seasonally adjusted? | Baseline 2010Q1–2019Q4 |
| --- | --- | --- | --- | --- |
| KOR DSR (BIS) | 2009-Q1 | 2026-Q1 | No (all BIS DSR series are unadjusted) | ✅ complete |
| JPN real income per capita (OECD Household Dashboard) | 2009-Q1 | **2025-Q1** | Yes | ✅ complete |
| JPN nominal income (OECD sector accounts) | 2009-Q1 | **2025-Q1** | **No** | ✅ complete |
| KOR real income per capita | **not published** by OECD | — | — | — |
| KOR nominal income (OECD sector accounts) | **2010-Q1** | **2024-Q4** | **No** | ✅ exactly 40 quarters |
| Household consumption deflator inputs (JPN, KOR) | 2009-Q1 | 2026-Q2/Q3 | Both | ✅ |
| Population (all 7) | 2009-Q1 | KOR 2025-Q4, others 2026 | Both | ✅ |

**Conclusions**
- `baseline_window_override` can stay **empty**: every series covers 2010-Q1 to 2019-Q4.
- KOR real income per capita has to be **built** as nominal income ÷ household consumption deflator ÷ population. For consistency I propose building K1 the same way for **all 7 countries**. That gives the contract's unit (national currency per person) instead of the dashboard's index, and keeps OECD's dashboard series as a cross-check.
- JPN and KOR nominal income are not seasonally adjusted, so seasonal adjustment needs a method (see §3).

### D4 — Population denominator

- `DF_QNA_POP_EMPNC` (POP, seasonally adjusted) covers all 7 countries from 2009. It ends at 2026-Q3 for most, 2026-Q1 for AUS and 2025-Q4 for KOR.
- The current H1 input (`B1GQ_POP`) is OECD's own per-capita GDP in **USD PPP**. That conflicts with the contract unit ("national currency per person") and uses OECD's internal population figure.
- **Proposal:** H1 = GDP chain-linked volume in national currency (`DF_QNA`, B1GQ, LR, table T0102, seasonally adjusted, available for all 7 from 2009) ÷ population. K1 is built with the same population series. Both series keys go into the metadata.

### D5 — Equities

- **The named benchmarks are licensed products:** S&P 500 (S&P DJI), TSX (S&P/TMX), FTSE 100 (FTSE Russell), DAX (STOXX), ASX 200 (S&P), Nikkei 225 (Nikkei Inc.), KOSPI (KRX). Free sources such as Yahoo or Stooq don't grant redistribution rights.
- **OECD's national share price index** (`DF_FINMARK`, monthly, all 7, 2009-01 to 2026-10, no gaps) is published under OECD's open data terms. I'll confirm the exact licence wording before lock.
- **Proposal:** H2 = the OECD share price index, averaged over the quarter and divided by BIS headline CPI. Publish `h2_real_equity_raw` normally. Methodology §2 and the contract table would then name "OECD national share price index" as the H2 source, with the benchmarks mentioned as context only.

### D7 — Deflators

| Use | Series | Reason |
| --- | --- | --- |
| H2 real equity | **BIS `WS_LONG_CPI`, `M.{country}.628`** (headline CPI index) | One source for all 7. Monthly to 2026-09 (AUS to 2026-06, quarterly underneath). OECD's headline CPI for Japan ends at 2021-Q2. |
| K1 real income | Household consumption deflator = current-price ÷ volume household final consumption (OECD `DF_QNA`, P31DC) | Matches the methodology. It's available for all 7, including KOR. JPN and KOR have it only for the household sector proper (S14), while the income series also covers non-profits serving households (S1M). I'll note that in the metadata. |

The exact series keys will be logged in `pipeline_metadata.json → indicators.*.series_keys`, as the contract requires.

---

## 2. Sanity checks you asked for

**a. Additive contributions in z-units (§3.4): ✅ agree.** This matches Methodology v0.1 §6 and is the right call. One mismatch to fix: **how shares are calculated**.
- The contract (§4) uses `shares = contributions / divergence_gap_z`.
- The methodology uses `|contribution| ÷ Σ|contributions|`.

Even above the 0.25σ threshold, dividing by Δ gives negative shares or shares above 100% whenever contributions have mixed signs. For example, with H2 = +0.9 and K1 = −0.6, Δ = 0.3, so H2's share is 300%. **Recommendation:** use the methodology's absolute-share formula in §4.

**b. Wide panel, one row per country-quarter (D1): ✅ agree.** A long table can come in v1.1.

**c. Other places where the contract and Methodology v0.1 (both dated 2026-11-21) disagree** — these need settling before lock:

| Topic | Contract | Methodology v0.1 | Suggested fix |
| --- | --- | --- | --- |
| How z-scores are calculated (§3.2) | Same 2010–19 mean/SD rule for every indicator | H1, H2 and K1 are **detrended**: log, fit a linear trend, score the residuals. Mean/SD applies only to H3, K2, K3, K4. | Use the methodology wording in §3.2. Add `z_baseline_stats` trend coefficients (α, β, σ_e) for H1, H2, K1. |
| K4 definition | Food & energy price level | Food & energy CPI ÷ nominal income per capita | Pick one. The methodology version changes K4's unit and which data it needs. |
| Model 2 composites (§3.3) | `headline_idx100`, `kitchen_table_idx100`, `divergence_gap_idx100` included | §8 says to **drop** them (equities would dominate) | Drop them. The column count goes from 41 to **38**. |
| Q7 polarity check | corr(raw, z) has the expected sign | For detrended series, raw rises with the trend while z doesn't, so the correlation can come out with the "wrong" sign even when the code is right | For H1, H2, K1, compare z with the detrended log value instead of raw. Keep raw-vs-z for the mean/SD indicators. |
| `quarter` key | `YYYY-Qn` | — | Matches what the data uses (`2024-Q3`). ✅ |

**d. Validation spec (§7):** agreed as the pytest/pandera spec. Q5 (ddof = 1) also holds for detrended series as long as σ_e is computed with ddof = 1 on the baseline residuals.

---

## 3. Consequence: the panel end date

The current latest complete quarter per country, given the gaps above:

| Bottleneck | Country | Ends |
| --- | --- | --- |
| Food & energy CPI (OECD) | JPN | 2021-Q2 |
| Nominal household income | KOR | 2024-Q4 |
| Household income (real and nominal) | JPN | 2025-Q1 |
| Food & energy CPI | CAN | 2025-Q1 |
| BIS DSR | all | 2026-Q1 |

**Options**

1. **Add national sources for the gaps.** These are all free; Japan and Korea need a free API key:
   - Japan CPI (e-Stat)
   - Korean household income (Bank of Korea ECOS)
   - Canadian CPI (Statistics Canada)
   - Australian energy CPI (ABS)

   *Recommended.* Each is one more stream in the Airbyte connectors.
2. **Accept 2024-Q4** as the first published common quarter and disclose it.
3. **Drop a country from the composite** for quarters it can't cover. This is the methodology's open item on series that end early; it currently only covers series that *start* late.

**Seasonal adjustment** is still open (methodology §11). The series that need it are K2 (all countries), the K4 CPI components (all countries), and JPN/KOR nominal income. My suggestion: X-13ARIMA-SEATS via `statsmodels`, falling back to STL, run once per vintage, with the method recorded in `sa_status`.

---

## 4. What I need from you

- [ ] D2: are fixed 2015–19 weights OK, or do you want chain-linked annual weights?
- [ ] K4 definition: the price level (contract) or ÷ income (methodology)?
- [ ] OK to rebuild H1 and K1 from components (D3/D4) instead of using OECD's ready-made per-capita series?
- [ ] H2 = OECD share price index (D5)?
- [ ] Panel end date: option 1, 2 or 3 above?
- [ ] Fix contract §3.2 (z-score method), §3.3 (drop idx100 composites), §4 (share formula) and Q7 (polarity check), or should I propose the edits in a PR?
