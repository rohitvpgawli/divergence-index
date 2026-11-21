"""Load bronze Parquet vintages into the local DuckDB warehouse.

    uv run python pipeline/ingest/load_bronze.py

Creates `data/warehouse.duckdb` with a `bronze` schema:

    bronze.<stream>        one table per Airbyte stream, ALL vintages stacked,
                           with a `vintage` (DATE) column from the folder name
    bronze.ingest_runs     one row per stream per ingestion run (row counts)

Bronze stays raw: values are the source strings, nothing is filtered or cast.
Picking the latest vintage, typing and cleaning happen in dbt (models/staging).
The Parquet files remain the durable copy; this database can be rebuilt any time.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
BRONZE = ROOT / "data" / "bronze"
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"


def load(db_path: Path = WAREHOUSE) -> dict[str, int]:
    streams = sorted(p.name for p in BRONZE.iterdir() if p.is_dir() and not p.name.startswith("_"))
    counts: dict[str, int] = {}
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        for stream in streams:
            glob = (BRONZE / stream / "vintage=*" / "data.parquet").as_posix()
            con.execute(
                f"""
                CREATE OR REPLACE TABLE bronze.{stream} AS
                SELECT * EXCLUDE (vintage), CAST(vintage AS DATE) AS vintage
                FROM read_parquet('{glob}', hive_partitioning = true, union_by_name = true)
                """
            )
            counts[stream] = con.execute(f"SELECT count(*) FROM bronze.{stream}").fetchone()[0]

        runs = (BRONZE / "_runs" / "*.json").as_posix()
        con.execute(
            f"""
            CREATE OR REPLACE TABLE bronze.ingest_runs AS
            SELECT CAST(r.vintage AS DATE) AS vintage,
                   CAST(r.finished_at AS TIMESTAMPTZ) AS finished_at,
                   s.key AS stream,
                   CAST(json_extract(s.value, '$.source') ->> '$' AS VARCHAR) AS source,
                   CAST(json_extract(s.value, '$.rows') AS INTEGER) AS row_count
            FROM read_json('{runs}', format = 'auto', columns = {{
                     vintage: 'VARCHAR', finished_at: 'VARCHAR', streams: 'JSON'}}) r,
                 json_each(r.streams) s
            """
        )
    return counts


if __name__ == "__main__":
    for stream, n in load().items():
        print(f"  bronze.{stream:36s} {n:>6d} rows")
    print(f"-> {WAREHOUSE.relative_to(ROOT)}")
