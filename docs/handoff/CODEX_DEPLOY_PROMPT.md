# Hand-off prompt: deploy the Divergence Index pipeline to EC2 (Dagster → PyAirbyte → dbt → MotherDuck)

> Paste everything below the line into Codex. Written 2026-11-22 against commit `ed69900` on `main`.

---

## Role and goal

You are working in the `divergence-index` repo (GitHub: `rohitvpgawli/divergence-index`). A data pipeline already runs end to end on a laptop. Your job is to make it run **unattended once a month on one EC2 instance**, and to publish the final gold tables to **MotherDuck**.

The target flow:

```
EC2 (ap-south-1), one Dagster job "monthly_refresh", schedule: 15th of each month, 06:00 UTC
  1. ingest   PyAirbyte runs the existing YAML manifests → Parquet in S3 (same layout Airbyte OSS writes today)
  2. build    dbt build (dbt-duckdb, local DuckDB file on the instance, reading bronze from S3)
  3. export   pipeline/publish/export_gold.py (existing contract checks Q8/Q9; writes data/gold/)
  4. publish  copy the gold tables to MotherDuck + the four gold files to S3, all or nothing
```

**Do not change methodology or model logic.** Leave the SQL under `pipeline/transform/models/`, the seeds, the contract tests, the gold column set and its order, and `docs/DATA_CONTRACT.md` as they are. Gold is 38 columns because of `include_idx100_composites=false`. If something only works by changing a model, stop and explain why in the PR instead.

Before writing code, read these files: `README.md`, `docs/DATA_MODEL.md`, `docs/AIRBYTE_CONNECTORS.md`, `docs/TODO.md` (Platform section), `pipeline/ingest/run_ingest.py`, `pipeline/transform/profiles.yml`, `pipeline/transform/dbt_project.yml`, `pipeline/transform/macros/stg_sdmx.sql`, `pipeline/transform/models/staging/_sources.yml`, `pipeline/publish/export_gold.py`, and `infra/aws/*.json`.

## Decisions already made (don't re-open these)

- **No Airbyte OSS server on EC2.** PyAirbyte runs the declarative manifests in `pipeline/ingest/airbyte/manifests/` in-process. Don't install `abctl`, Docker or Kubernetes.
- **Dagster is the only scheduler.** There is no Airbyte cron and no system crontab. dbt runs only if ingest succeeded, and publish runs only if dbt plus export succeeded.
- **dbt builds in a local DuckDB file on the instance, not in MotherDuck.** The profile pins DuckDB to `threads: 1` so that gold is byte-deterministic. Keep that setting.
- **MotherDuck receives a copy of gold only after every check passes.** A failed run must leave the previous MotherDuck gold untouched (contract §0.4: fail loudly, never overwrite the last good gold).
- **Region `ap-south-1`. Bucket `divergence-index-data-lqpeej`.**
- **Python 3.12, managed by `uv`.** Add dependencies to `pyproject.toml` and commit `uv.lock`.
- **No secrets in the repo**, ever. That covers AWS keys, the MotherDuck token and webhook URLs.

## The one contract you must not break: the bronze S3 layout

dbt reads bronze from S3 and identifies a sync **by file name**. Today Airbyte OSS writes, for example:

```
s3://divergence-index-data-lqpeej/airbyte/oecd/k4_cpi_components/2026_11_22_1795369809600_0.parquet
s3://divergence-index-data-lqpeej/airbyte/oecd/k4_cpi_components/2026_11_22_1795369809600_1.parquet
s3://divergence-index-data-lqpeej/airbyte/bis/k2_household_dsr/2026_11_22_1795373542618_0.parquet
```

- The path is `airbyte/<source>/<stream>/<YYYY_MM_DD>_<sync start, epoch ms, 13 digits>_<part>.parquet`, where `<source>` is `oecd` or `bis`.
- Every stream in one run must share the **same** epoch-ms sync id, and parts count from `_0`.
- `macros/stg_sdmx.sql` → `bronze_sync_id()` pulls the id out with the regex `_(\d{13})_\d+\.parquet$`. Staging then keeps only rows where `_sync_id = max(_sync_id)` for that stream. **A partly written sync with a newer id would silently replace a complete one.** So upload all files to a temporary prefix first, then copy them into place, or write the parts in an order where a failure leaves no file at the final key. Document which approach you chose.
- Columns: the stream's data columns, all `VARCHAR`: `source, indicator_id, dataflow, ref_area, freq, time_period, obs_value, obs_status, unit_measure, series_variant, raw` (with `raw` as JSON text). Add `_airbyte_raw_id` (VARCHAR) and `_airbyte_extracted_at` (TIMESTAMPTZ) as well. The Airbyte OSS files also carry `_airbyte_meta` and `_airbyte_generation_id`. They're optional because sources use `union_by_name = true`, but keep the types consistent if you add them.
- Old syncs are kept and never deleted. Bronze is an append-only history.

Extend `pipeline/ingest/run_ingest.py`, don't fork it. Add a destination option, for example `--dest local` (today's behaviour: `data/bronze/<stream>/vintage=…/data.parquet` plus `load_bronze.py`) and `--dest s3`. Put the S3 writer in a separate module. The existing local mode and `bronze_source: local` must keep working.

**Offline test of the layout:** dbt already accepts a local path as `s3_bronze_root`, and `read_parquet(..., filename=true)` plus the regex work on local files. Write the S3 layout to a local mirror folder (for example `--dest s3 --s3-root data/_s3_mirror/airbyte`). Then run `dbt build --vars '{bronze_source: s3, s3_bronze_root: data/_s3_mirror/airbyte}'`. This lets you prove the contract without AWS credentials. Git-ignore the mirror folder.

## Work items

### A. Dagster project: `pipeline/orchestration/`

- Add the packages `dagster`, `dagster-webserver` and `dagster-dbt`. Use either a `definitions.py` with assets or a job built from ops; pick whichever stays simplest. Assets are preferred, so the UI shows ingest → dbt models → publish lineage.
- **dbt via dagster-dbt:** dagster-dbt writes each invocation's artifacts to its own target folder by default. `export_gold.py` hard-codes `pipeline/transform/target/run_results.json`. Make `export_gold.py` accept the run-results path as an argument or an env var (`DBT_RUN_RESULTS`), keeping the default. Don't weaken its "refuse to publish after a failed build" check.
- dbt must run the **full** `dbt build`: seeds, models, unit tests and contract tests. Warnings are allowed. Errors and failures stop the run before export.
- Schedule: `0 6 15 * *`, timezone UTC. Also allow a manual launch from the UI.
- Failure alert: add a run-failure sensor. If env `ALERT_WEBHOOK_URL` is set, POST a short Slack-compatible JSON message (job, failed step, run id). Otherwise only log. Don't hard-code a URL.
- Run configuration comes from env vars, with defaults that match today: `DUCKDB_PATH`, `DIVERGENCE_AWS_PROFILE`, a new `DIVERGENCE_AWS_CHAIN` (see B), `MOTHERDUCK_TOKEN`, `MOTHERDUCK_DATABASE` (default `divergence_index`), `ALERT_WEBHOOK_URL`.
- Dagster instance storage: SQLite under `DAGSTER_HOME` is enough.

### B. AWS credentials on EC2 (no static keys)

- `profiles.yml` today uses `provider: credential_chain, chain: config, profile: divergence-reader`. On EC2 the credentials come from the **instance role**. Make the chain configurable through `DIVERGENCE_AWS_CHAIN`: default `config` on the laptop, set to `instance` on EC2 (check DuckDB's `aws` extension docs for the exact chain names). Leave the laptop behaviour unchanged.
- Write `infra/aws/ec2-pipeline-role-policy.json`, one policy for the instance role. It needs:
  - list the bucket
  - read and write under `airbyte/*`, so ingest can write and dbt can read
  - read and write under `gold/*`
  - `ssm:GetParameter` on `arn:aws:ssm:ap-south-1:<ACCOUNT_ID>:parameter/divergence/*`, with decrypt for the default `aws/ssm` key
- Also add `infra/aws/ec2-trust-policy.json`, and note that the role needs the AWS-managed `AmazonSSMManagedInstanceCore` policy for Session Manager.
- Keep the existing two policy files. They still serve the laptop users.

### C. Publish to MotherDuck: `pipeline/publish/publish_motherduck.py`

- Runs after `export_gold.py` succeeds. Read from the local warehouse (read-only) and write to `md:<MOTHERDUCK_DATABASE>`, using `MOTHERDUCK_TOKEN` from the environment.
- Published surface. Keep column names and order exactly as in the source:

  | MotherDuck table | Source |
  | --- | --- |
  | `gold.divergence_panel` | `gold.gld_divergence_panel` (same 38 columns as `data/gold/divergence_panel.parquet`) |
  | `gold.indicator_scores` | `gold.gld_indicator_scores` |
  | `gold.baseline_stats` | `gold.gld_baseline_stats` |
  | `reference.dim_indicator`, `reference.countries` | seeds |
  | `silver.indicator_quarterly` | `silver.slv_indicator_quarterly` (context charts) |
  | `meta.pipeline_metadata`, `meta.component_contributions` | one row each: `run_id`, `published_at`, and the JSON document from `data/gold/` |
  | `meta.publish_log` | **append**, one row per successful publish: `run_id`, `git_commit`, `published_at`, row counts per table, `latest_complete_common_quarter` |

- **All or nothing.** Replace every table in a single transaction. First check whether MotherDuck supports a multi-statement transaction for this with a local source attached. If it doesn't, write `*__next` tables, check their row counts, and then swap them in. Document what you did. Run a check after publishing: the MotherDuck panel row count and column list must equal the Parquet file's.
- Also upload the four files in `data/gold/` to `s3://divergence-index-data-lqpeej/gold/runs/<run_id>/` (immutable, never overwritten). **Don't copy files into `gold/latest/`.** S3 can't update several objects atomically, and S3 and MotherDuck can't commit together. Instead, after the MotherDuck publish succeeds, write one small object `gold/latest.json` containing `{run_id, published_at, prefix}`. That single-object write is the S3 "commit". MotherDuck is the source of truth for the dashboard; S3 is the archive and rollback copy. Order: (1) upload the run folder, (2) MotherDuck swap, (3) write `gold/latest.json`. A failure at step 3 is logged loudly but doesn't roll back MotherDuck; the next run repairs it.
- Add a `--dry-run` flag that prints the planned operations without connecting to MotherDuck or S3.

### D. EC2 setup: `infra/ec2/`

- Target: Ubuntu 24.04 LTS, `t3.medium`, 30 GB gp3, ap-south-1, the instance role from B. The security group has **no inbound rules**. Admin access goes through SSM Session Manager, and the Dagster UI is reached through SSM port forwarding to `127.0.0.1:3000`.
- `infra/ec2/bootstrap.sh`, idempotent, run on the instance:
  - creates a `divergence` system user
  - installs `uv` and git
  - clones the repo to `/opt/divergence-index`
  - runs `uv sync --frozen`
  - creates `DAGSTER_HOME=/var/lib/divergence/dagster` and `DUCKDB_PATH=/var/lib/divergence/warehouse.duckdb`
  - installs the systemd units
- `infra/ec2/fetch-secrets.sh`: reads the SSM SecureString parameters `/divergence/motherduck_token` and (optionally) `/divergence/alert_webhook_url`, then writes `/etc/divergence/env` with mode `600`, owner `divergence`. It runs as `ExecStartPre` of the units.
- systemd units:
  - `dagster-daemon.service` (schedules and sensors)
  - `dagster-webserver.service`, bound to `127.0.0.1:3000` only

  Both units run as `divergence`, use `EnvironmentFile=/etc/divergence/env` and `Restart=on-failure`.
- Updating code: write a short `infra/ec2/deploy.sh` (`git pull`, `uv sync --frozen`, restart the units). No CI/CD is needed.
- The repo tracks `data/bronze/` and `data/gold/`. On EC2 those copies are scratch, so the instance must never commit or push.

### E. Docs and housekeeping

- `docs/DEPLOYMENT.md`, a runbook Rohit can follow step by step with copy-paste AWS CLI commands:
  - create the role and instance profile
  - put the SSM parameters
  - launch the instance
  - run the bootstrap
  - open the UI through a port-forward
  - trigger a manual run
  - read the logs (`journalctl`)
  - roll back to the last good gold (S3 `gold/runs/<run_id>/` and `meta.publish_log`)
  - create a **read-only MotherDuck token** for Juhi (Settings → Access tokens → read scaling token). Note that it reaches every database on the account.
- Update the Platform items in `docs/TODO.md` and the run instructions in `README.md`.
- Add `.gitignore` entries for the local S3 mirror and any Dagster local storage.

## What not to do

- Don't run anything against real AWS, S3 or MotherDuck unless credentials are present **and** Rohit has said to. Build and test everything offline (local S3-layout mirror, `--dry-run`), and leave the AWS steps in the runbook for Rohit.
- Don't delete or rewrite any existing S3 object, bronze vintage, or `data/gold/` file.
- Don't change dbt vars that encode methodology decisions (`k4_definition`, `include_idx100_composites`, baseline windows, `cpi_weight_years`).
- Don't add an Airbyte server, Docker, Kubernetes, Terraform state backends, or a second scheduler.
- Don't commit tokens, account IDs or webhook URLs. Use `<ACCOUNT_ID>` placeholders in policy files.

## Done means

1. `uv run pytest` passes. Add tests for:
   - the S3 key format and that it matches the `bronze_sync_id()` regex
   - all streams in one run sharing one sync id
   - a failed upload leaving no file at a final key
   - `export_gold.py` honouring `DBT_RUN_RESULTS`
   - `publish_motherduck.py --dry-run` listing exactly the tables in section C
2. Offline end-to-end check:
   - `run_ingest.py --dest s3 --s3-root data/_s3_mirror/airbyte`, then `dbt build` against the mirror, then `export_gold.py` all succeed
   - the result has 38 columns
   - running `dbt build` and `export_gold.py` again on the same bronze gives **byte-identical** `divergence_panel.parquet` and `.csv`
3. `uv run dagster definitions validate` (or the equivalent for the installed version) passes. `dagster dev` shows the job, the monthly schedule and the failure sensor. A manual run against the local mirror goes green from ingest through export, with publish in dry-run mode.
4. The laptop flow is unchanged: `uv run dbt build --project-dir pipeline/transform --profiles-dir pipeline/transform` still reads S3 with the `divergence-reader` profile.
5. All work is on a branch named `deploy/ec2-dagster`, opened as one PR. The PR description lists:
   - every new env var
   - every AWS resource Rohit has to create
   - how the all-or-nothing publish works
   - anything you couldn't verify offline

## Known quirks in this repo

- PyAirbyte telemetry is turned off with `DO_NOT_TRACK=1`. Keep it off.
- The manifests use declarative runtime `version: 7.49.0`. PyAirbyte resolves this through `airbyte-cdk`, so no Airbyte database fix is needed.
- `k4_cpi_components` produces more than one Parquet part per sync. The code must handle any number of parts.
- BIS and OECD may be synced separately. `stg_sdmx` takes the latest sync **per stream**, so one sync id per run is fine. Don't assume all streams always have the same id across runs.
- `latest_complete_common_quarter` is currently 2021-Q2 because of a Japan CPI data gap (`docs/TODO.md`). This is expected and is not a bug for you to fix.
- One dbt test (`z_extreme_values_warn`) is expected to **warn**. Warnings must not fail the run.
