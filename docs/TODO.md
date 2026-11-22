# To-do

Open items that sit outside the current build. Newest first within each section.

## Data gaps (these set the panel end date)

- [ ] **Japan food & energy CPI after 2021-Q2.** OECD `DF_PRICES_ALL` stops at 2021-Q2 for Japan, so Japan's K4 (and with it `latest_complete_common_quarter`) ends there. Add a Japanese source (Statistics Bureau of Japan / e-Stat API, which needs a free app ID) as a new Airbyte stream. Then splice it into `slv_k4_essentials` after 2021-Q2, with a documented splice method. *(Raised 2026-11-22.)*
- [ ] **Korea household disposable income after 2024-Q4.** OECD QSA ends at 2024-Q4 and is NSA only. Candidate: Bank of Korea ECOS API (free key).
- [ ] **Canada food & energy CPI after 2025-05, Australia energy CPI after 2025-Q2.** Candidates: Statistics Canada API (table 18-10-0004), ABS Data API. Neither needs a key.

## Methodology / contract (with Juhi)

- [ ] Answers to `docs/DATA_CONTRACT_REVIEW.md` §4: K4 definition, fixed vs chained CPI weights, panel end-date rule, z-score method wording, idx100 composites, share formula, Q7 polarity check.
- [ ] Seasonal adjustment method for NSA inputs: K2 (all), K4 CPI components (all), JPN/KOR nominal household income. Proposed: X-13ARIMA-SEATS via statsmodels, falling back to STL.
- [ ] Bump `DATA_CONTRACT.md` to v1.0.0 once the decisions above are settled.

## Platform

- [ ] Move to EC2 (ap-south-1): Airbyte connections on a monthly cron (`0 6 15 * *`), dbt reading S3, gold copied to `s3://…/gold/` with a gold-writer IAM user.
- [ ] dbt source freshness on S3 (`_airbyte_extracted_at`): warn if the latest sync is older than 40 days.
- [ ] Revision alerts: compare the latest vs previous sync per series (contract §6 `revision_alerts`).
- [ ] Re-register the declarative-manifest runtime v7 in Airbyte's DB after any reinstall (the cron updater gets a 403 from Docker Hub).
