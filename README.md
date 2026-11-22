# Divergence Index

The pipeline ingests OECD and BIS SDMX data, builds the divergence index in a local DuckDB warehouse, and exports the dashboard's gold data. See the [data model](docs/DATA_MODEL.md) and [contract](docs/DATA_CONTRACT.md).

## Laptop

Run these commands from the repository root with Python 3.12 managed by `uv`.

```bash
uv sync --frozen
uv run pytest
uv run dbt build --project-dir pipeline/transform --profiles-dir pipeline/transform
uv run python pipeline/publish/export_gold.py
```

The default dbt target reads S3 using the `divergence-reader` AWS profile. Use the offline target to refresh from local PyAirbyte Parquet.

```bash
uv run python pipeline/ingest/run_ingest.py
uv run dbt build --project-dir pipeline/transform --profiles-dir pipeline/transform \
  --target offline --vars '{bronze_source: local}'
uv run python pipeline/publish/export_gold.py
```

## EC2 and offline verification

The `monthly_refresh` Dagster job runs at 06:00 UTC on the 15th. It writes bronze Parquet to S3, runs the full dbt build locally, checks the four gold exports, and publishes to MotherDuck and S3. The [deployment runbook](docs/DEPLOYMENT.md) covers AWS setup, the local mirror and dry run, manual launches, and recovery.
