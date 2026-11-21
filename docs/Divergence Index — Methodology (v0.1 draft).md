# Divergence Index — Methodology (v0.1 draft)

Nov 21, 2026 · @Juhi Vajpayee Gawli

## 1. Purpose and scope

The Divergence Index measures, for each country and quarter, how far "Headline" macro performance sits above or below household ("Kitchen Table") conditions, each relative to that country's own pre-2020 norm. This document is the formal specification the engineering pipeline implements and the narrative cites.

- **Cohort (N = 7):** United States (USA), Canada (CAN), United Kingdom (GBR), Germany (DEU), Australia (AUS), Japan (JPN), South Korea (KOR).
- **Frequency:** quarterly.
- **Analysis window:** Q1 2010 to the latest common complete quarter (Section 7).
- **Reference period:** Q1 2010 – Q4 2019 (40 quarters). All trends, means and standard deviations are estimated on this window only, then held fixed.
- **Two outputs:** Model 1, the standardized Divergence Gap (primary, used for all claims); Model 2, a Q4 2019 = 100 rebased index (visual companion only, Section 8).

## 2. Indicator set

Seven indicators in two baskets. "Treatment" says how each is standardized (Section 4): growth series are detrended; ratios are scored on their level.

| Code | Basket | Indicator | Definition | Source | Polarity (s) | Treatment |
| --- | --- | --- | --- | --- | --- | --- |
| H1 | Headline | Real GDP per capita | Chained-volume GDP ÷ population, seasonally adjusted (SA) | OECD Quarterly National Accounts | +1 (higher = better) | Detrended |
| H2 | Headline | Real equity index | Quarterly average of national benchmark index (S&P 500, TSX, FTSE 100, DAX, ASX 200, Nikkei 225, KOSPI) ÷ headline CPI | Market data; OECD CPI | +1 | Detrended |
| H3 | Headline | Unemployment rate | Harmonized unemployment rate, %, SA, quarterly average | OECD | −1 (lower = better) | Level |
| K1 | Kitchen Table | Real household disposable income per capita | Household gross disposable income ÷ population, deflated by household consumption deflator, SA | OECD household sector accounts | +1 | Detrended |
| K2 | Kitchen Table | Household debt service ratio (DSR) | Interest + principal payments as % of household disposable income | BIS | −1 | Level |
| K3 | Kitchen Table | House price-to-income ratio | Nominal house prices ÷ nominal disposable income per head, index | OECD Analytical House Prices | −1 | Level |
| K4 | Kitchen Table | Essentials-to-income ratio | Food & energy CPI ÷ nominal household disposable income per capita (both indexed, 2015 = 100), quarterly | OECD CPI (COICOP food, energy); same income series as K1 before deflation | −1 | Level |

**Change from the original spec (K4):** K4 was the nominal food & energy price level. It is now essential prices relative to household income, so all three Kitchen Table burden measures (K2, K3, K4) share the form cost ÷ income. The nominal version ignored income growth and deteriorated mechanically under any positive inflation target.

**Known overlap:** K1 and K4 share the income series, so they will be correlated. This is disclosed and tested in the leave-one-out check (Section 9).

## 3. Data preparation

All series are converted to quarterly, seasonally adjusted values in national currency before any standardization.

1. **Frequency alignment.** Monthly series (H2, H3, CPI components for K4) are averaged over the three months of each quarter. Daily equity closes are averaged over the quarter.
2. **Seasonal adjustment.** Use the source's SA series where published. Where only non-SA data exist, flag the series in pipeline metadata; method for adjusting it is an open item (Section 11).
3. **Deflation of equities (H2).** Real index = nominal quarterly average ÷ headline CPI × 100.
4. **Construction of K4.** Rebase food & energy CPI and nominal household disposable income per capita to 2015 = 100, then K4 = CPI index ÷ income index × 100. The food and energy weights follow each country's own CPI basket.
5. **Logs for growth series.** H1, H2 and K1 are converted to natural logs before detrending (Section 4), so the trend is a constant growth rate and deviations read as approximate % gaps.

```latex
E^{real}_{i,t} = \frac{E^{nom}_{i,t}}{P_{i,t}} \times 100 \qquad K4_{i,t} = \frac{CPI^{F\&E}_{i,t}}{Y^{nom}_{i,t}} \times 100
```

Where i = country, t = quarter, P = headline CPI, Y = nominal household disposable income per capita.

## 4. Standardization

Every indicator becomes a z-score: how many standard deviations (σ) it sits from its 2010–19 norm, signed so that higher always means better for households or the economy. Growth series are measured against their pre-2020 trend path; ratios against their pre-2020 average level.

**Why two treatments.** Series that grow with the economy (H1, H2, K1) would look extreme in any recent quarter simply because they keep growing, producing a gap that is just the passage of time. Ratios (H3, K2, K3, K4) have no built-in growth, and projecting their 2010–19 drift forward can produce impossible values (for example, US unemployment fell from about 10% to 3.5% over the decade; its trend extrapolates below zero).

### 4a. Growth series (H1, H2, K1): deviation from log-linear trend

Fit a straight line to the log of the series over the reference window, project it forward, and score each quarter's distance from that line.

```latex
\ln x_{k,i,t} = \alpha_{k,i} + \beta_{k,i}\, t + e_{k,i,t} \quad \text{(estimated on 2010Q1–2019Q4)}
```

```latex
z_{k,i,t} = s_k \cdot \frac{\ln x_{k,i,t} - (\hat\alpha_{k,i} + \hat\beta_{k,i}\, t)}{\hat\sigma_{e,k,i}}
```

Where σ̂\_e is the standard deviation of the reference-window residuals. The trend coefficients are fixed after estimation and are not re-fitted as new quarters arrive.

### 4b. Ratios (H3, K2, K3, K4): deviation from reference-period level

```latex
z_{k,i,t} = s_k \cdot \frac{x_{k,i,t} - \mu_{k,i}}{\sigma_{k,i}}
```

Where μ and σ are the mean and standard deviation over 2010Q1–2019Q4.

### 4c. Properties and caveats

- By construction, every z-score has mean 0 and standard deviation 1 over the reference window. The pipeline tests this.
- Smooth series (especially H1) have small reference-window σ, so shocks such as 2020Q2 will register as very large z-scores (potentially beyond −10σ). This is expected, not an error; charts should handle the range.
- The 2010–19 window starts in the post-2008 recovery and includes a long equity bull market. A steep fitted trend for H2 may make later equity performance look weaker than it is. Tested in Section 9.
- K4 may still drift over 2010–19 if incomes grew faster than essential prices. If the real data show a clear reference-period trend in K4, revisit its treatment (open item, Section 11).

## 5. Sub-indices and the Divergence Gap

The Divergence Gap Δ is the Headline average minus the Kitchen Table average, in σ units. Δ > 0 means the headline economy is further above its norm than households are.

```latex
H_{i,t} = \tfrac{1}{3}\left(z_{H1} + z_{H2} + z_{H3}\right) \qquad K_{i,t} = \tfrac{1}{4}\left(z_{K1} + z_{K2} + z_{K3} + z_{K4}\right)
```

```latex
\Delta_{i,t} = H_{i,t} - K_{i,t}
```

- **Weights:** equal within each basket (⅓ Headline, ¼ Kitchen Table). Alternative weights are tested in Section 9.
- **Reading Δ:** a value of 1.0 means Headline conditions are one standard deviation further above their norm than Kitchen Table conditions. Δ is comparable across countries because each country is measured against its own history, not against other countries' levels.
- **Not comparable:** H or K levels across countries in absolute terms (for example, "Australia's households are worse off than Germany's"). The index supports claims about change relative to each country's own norm only.

## 6. Contribution decomposition

Each indicator's contribution to Δ is reported in σ units, and the seven contributions sum exactly to Δ. Headline indicators enter with weight +⅓; Kitchen Table indicators enter with weight −¼, because Δ subtracts K.

```latex
C_{k,i,t} = w_k \cdot z_{k,i,t}, \qquad w_k = \begin{cases} +\tfrac{1}{3} & k \in \{H1,H2,H3\} \\ -\tfrac{1}{4} & k \in \{K1,K2,K3,K4\} \end{cases} \qquad \sum_k C_{k,i,t} = \Delta_{i,t}
```

**Worked example (illustrative values, not data):**

| Indicator | z-score | Weight | Contribution to Δ |
| --- | --- | --- | --- |
| H1 GDP | +1.0 | +⅓ | +0.33 |
| H2 Equities | +2.0 | +⅓ | +0.67 |
| H3 Unemployment | +0.3 | +⅓ | +0.10 |
| K1 Income | −0.2 | −¼ | +0.05 |
| K2 Debt service | −1.0 | −¼ | +0.25 |
| K3 Housing | −1.4 | −¼ | +0.35 |
| K4 Essentials | −0.6 | −¼ | +0.15 |
| **Total** |  |  | **+1.90 (= Δ)** |

A weak Kitchen Table score (negative z) produces a positive contribution: it widens the gap. A strong one narrows it.

**Change from the original spec:** the original formula divided each term by Δ to give percentage shares and implied +¼ weights for Kitchen Table items. That reversed the sign of every Kitchen Table contribution and produced unstable shares when Δ is near zero (Δ = 0.05 turns a 0.25 contribution into 500%).

**Percentages (display only):** where a caption needs shares, use each contribution's share of the sum of absolute contributions, not of Δ. Percentages are not shown when |Δ| < 0.25; captions then report σ contributions only.

## 7. Sample alignment

The composite is computed on a balanced panel: the same quarters for all seven countries and all seven indicators.

- **Start:** Q1 2010 for every country. All 40 reference quarters (Q1 2010 – Q4 2019) must be present for every indicator, or that country–indicator's trend and σ cannot be estimated.
- **End (latest common quarter):** the most recent quarter in which all 7 indicators are available for all 7 countries. Household income (K1, K4) and debt service (K2) typically lag 1–2 quarters, so the slowest series sets the end date for everyone.
- **No gap-filling in the composite:** missing values are not interpolated or carried forward inside the composite window. Any imputation used elsewhere is flagged per cell.
- **Fresher data:** quarters beyond the common end date may be shown as a separate "leading indicators" view (for example H2, H3, CPI) and are never folded into Δ.
- **If a series starts after Q1 2010** for any country, the choice between shortening the window for all countries and dropping the indicator for that country is deferred until the data availability check (Section 11).

**Required columns in the Gold output** (for the data contract): `is_latest_common_quarter` (true/false) and, per country and indicator, `latest_available_quarter`.

## 8. Dashboard companion index (Model 2: Q4 2019 = 100)

Model 2 rebases each raw indicator to Q4 2019 = 100 so readers can see "up 12% since before COVID." It is for visual storytelling only; all analytical claims use Model 1.

```latex
I_{k,i,t} = \frac{x_{k,i,t}}{x_{k,i,\,2019Q4}} \times 100 \quad (s_k = +1) \qquad I_{k,i,t} = 200 - \frac{x_{k,i,t}}{x_{k,i,\,2019Q4}} \times 100 \quad (s_k = -1)
```

For inverted indicators (H3, K2, K3, K4), the index falls when the burden rises, so downward always means worse.

**Limitation:** Model 2 is not variance-adjusted. Equities move far more than GDP or unemployment, so any Model 2 Headline average or gap will be driven mostly by H2. Model 2 is therefore published as individual indicator lines only, with no Model 2 Headline, Kitchen Table or gap series. The Gold output drops headline\_idx100, kitchen\_table\_idx100 and divergence\_gap\_idx100 and keeps the seven component idx100 columns.

## 9. Robustness checks

The headline finding stands only if Δ keeps the same sign and broad ranking across countries under each check below. Outputs go to `/analysis/robustness/`.

| # | Check | What changes | Critique it answers |
| --- | --- | --- | --- |
| R1 | **Growth-rate specification** | Replace detrended levels for H1, H2, K1 with z-scored year-on-year growth rates | "The result is an artefact of the trend you chose." |
| R2 | Trend window sensitivity | Re-fit trends on 2012Q1–2019Q4 (excludes post-2008 recovery) | "The 2010 start inflates the trend, especially for equities." |
| R3 | K4 alternative | K4 = food & energy CPI ÷ headline CPI (relative price) instead of ÷ income | "K4 double-counts income with K1." |
| R4 | Leave-one-out | Recompute Δ seven times, dropping one indicator each time (H2 equities first) | "It's just a stock market boom." |
| R5 | PCA weights | Replace equal weights with first-principal-component weights within each basket | "Equal weighting is arbitrary." |
| R6 | Vintage tracking | Store each quarterly data release; compare Δ across vintages | "Revisions to national accounts change the story." |

Hypothesis 3 in the research design (the gap persists after adjusting for differences in volatility) is tested by R1, R4 and R5 together rather than by a separate model.

## 10. Threats to validity

Five confounders from the research design carry over unchanged; two more arise from the decisions in this document.

| Threat | How it distorts Δ | Handling |
| --- | --- | --- |
| Public services in kind (healthcare, childcare) | US disposable income looks higher than in Germany or the UK, but US households pay more out of pocket | Cite OECD adjusted disposable income in country briefs. Δ is within-country, which limits but does not remove this. |
| Mortgage rate pass-through | 30-year fixed US mortgages shield existing owners; CAN, AUS, GBR, KOR reset faster | Note that US DSR understates stress for new buyers and renters. |
| Mean vs. median | H1 and K1 are per-capita averages; top-decile gains can lift them while median households fall behind | Present K1 as a conservative bound; the median gap is likely wider. |
| Reporting lags | K1 and K2 lag H2 and CPI by 1–2 quarters | Latest common quarter rule (Section 7). |
| Imported commodity shocks | Energy importers (DEU, JPN, KOR) see CPI spikes unrelated to domestic policy | Show K4 separately from K2/K3 in the decomposition chart. |
| **Trend choice (new)** | The fitted 2010–19 trend determines what counts as "normal" for H1, H2, K1 | R1 and R2. |
| **K1–K4 overlap (new)** | Both use household income, so an income shock moves both and is partly counted twice | Disclosed; R3 and R4. |
|  |  |  |

## 11. Decision log and open items

Eight decisions are settled; four items are open, two of which wait on Rohit's data availability check.

| Date | Decision | Section |
| --- | --- | --- |
| 2026-11-21 | Growth series (H1, H2, K1) are detrended against a log-linear 2010–19 trend; growth rates kept as robustness check R1 | 4a, 9 |
| 2026-11-21 | Ratios (H3, K2, K3, K4) are not detrended; scored against 2010–19 mean and σ | 4b |
| 2026-11-21 | K4 redefined as food & energy CPI ÷ nominal household disposable income per capita | 2, 3 |
| 2026-11-21 | Contributions reported in σ units with weights +⅓ (H) and −¼ (K); they sum to Δ | 6 |
| 2026-11-21 | Percentage shares shown only when | Δ |
| 2026-11-21 | Balanced panel: same quarters for all countries; end = latest common complete quarter | 7 |
| 2026-11-21 | Model 2 (Q4 2019 = 100) shown as individual indicator lines only; no Model 2 gap | 8 |
| 2026-11-21 | Only confirmed sources are cited. Drehmann, Juselius & Quincy (2024) and the \~114% Australian household debt-to-GDP figure are excluded unless verified | — |

**Open items**

- [ ] After real data arrive, check K4 for a clear 2010–19 trend and revisit its treatment if present (Section 4c).
- [ ] Data availability (Rohit): quarterly K1 for JPN and KOR; BIS household DSR for all 7 from 2010; licence-clean equity index history from 2010.
- [ ] Rule for a series that starts after Q1 2010: shorten window for all, or drop that indicator for that country (Section 7).
- [ ] Method for seasonally adjusting any series published only non-SA (Section 3).

&#32;
