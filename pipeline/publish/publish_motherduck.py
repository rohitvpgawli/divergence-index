"""Publish a checked local export to MotherDuck and S3."""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

if __package__:
    from .export_gold import GOLD, WAREHOUSE
    from ..ingest.s3_writer import BUCKET, s3_client
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from pipeline.publish.export_gold import GOLD, WAREHOUSE
    from pipeline.ingest.s3_writer import BUCKET, s3_client

TABLES = {
    "gold.divergence_panel": "gold.gld_divergence_panel",
    "gold.indicator_scores": "gold.gld_indicator_scores",
    "gold.baseline_stats": "gold.gld_baseline_stats",
    "reference.dim_indicator": "reference.dim_indicator",
    "reference.countries": "reference.countries",
    "silver.indicator_quarterly": "silver.slv_indicator_quarterly",
}
DOCUMENTS = {
    "meta.pipeline_metadata": "pipeline_metadata.json",
    "meta.component_contributions": "component_contributions.json",
}
FILES = ("divergence_panel.parquet", "divergence_panel.csv", *DOCUMENTS.values())
STAGED_TABLES = (*TABLES, *DOCUMENTS)


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def describe(con, relation):
    return [col[0] for col in con.execute(f"DESCRIBE {relation}").fetchall()]


def count(con, relation):
    return con.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]


def remote_publish(con, warehouse, gold, metadata, run_id, published_at):
    panel = pq.ParquetFile(gold / "divergence_panel.parquet")
    expected_rows = panel.metadata.num_rows
    expected_columns = panel.schema_arrow.names
    con.execute("CREATE SCHEMA IF NOT EXISTS meta")
    con.execute("""
        CREATE TABLE IF NOT EXISTS meta.publish_log (
            run_id VARCHAR PRIMARY KEY, git_commit VARCHAR, published_at TIMESTAMPTZ,
            row_counts JSON, latest_complete_common_quarter VARCHAR
        )
    """)
    latest = con.execute("""
        SELECT run_id FROM meta.publish_log ORDER BY published_at DESC, run_id DESC
    """).fetchone()
    committed = con.execute(
        "SELECT published_at FROM meta.publish_log WHERE run_id = ?", [run_id],
    ).fetchone()
    if committed:
        if latest != (run_id,):
            raise RuntimeError("A newer MotherDuck run is already published")
        verify_panel(con, expected_rows, expected_columns, "gold.divergence_panel")
        return committed[0]

    with duckdb.connect(str(warehouse), read_only=True) as local:
        source_panel = TABLES["gold.divergence_panel"]
        verify_panel(local, expected_rows, expected_columns, source_panel)
        difference = local.execute(
            f"SELECT * FROM {source_panel} EXCEPT ALL SELECT * FROM read_parquet(?) LIMIT 1",
            [str(gold / "divergence_panel.parquet")],
        ).fetchone()
        if difference is not None:
            raise RuntimeError("The warehouse panel differs from the checked export")

    for schema in ("gold", "reference", "silver"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    quoted_path = str(warehouse.resolve()).replace("'", "''")
    con.execute(f"ATTACH '{quoted_path}' AS local_warehouse (READ_ONLY)")
    counts = {}
    try:
        for target, source in TABLES.items():
            local_table = f"local_warehouse.{source}"
            staged = f"{target}__next"
            con.execute(f"CREATE OR REPLACE TABLE {staged} AS SELECT * FROM {local_table}")
            counts[target] = count(con, local_table)
            if count(con, staged) != counts[target] or describe(con, staged) != describe(con, local_table):
                raise RuntimeError(f"MotherDuck staging differs from {source}")
    finally:
        con.execute("DETACH local_warehouse")

    for target, filename in DOCUMENTS.items():
        document = (gold / filename).read_text()
        con.execute(
            f"CREATE OR REPLACE TABLE {target}__next AS "
            "SELECT ?::VARCHAR AS run_id, ?::TIMESTAMPTZ AS published_at, ?::JSON AS document",
            [run_id, published_at, document],
        )
        counts[target] = count(con, f"{target}__next")
        if counts[target] != 1:
            raise RuntimeError(f"Expected one metadata row in {target}__next")

    verify_panel(con, expected_rows, expected_columns, "gold.divergence_panel__next")
    con.execute("BEGIN TRANSACTION")
    try:
        for target in STAGED_TABLES:
            con.execute(f"DROP TABLE IF EXISTS {target}")
            con.execute(f"ALTER TABLE {target}__next RENAME TO {identifier(target.split('.')[1])}")
        con.execute("INSERT INTO meta.publish_log VALUES (?, ?, ?, ?::JSON, ?)", [
            run_id, metadata["git_commit"], published_at, json.dumps(counts),
            metadata["latest_complete_common_quarter"],
        ])
        verify_panel(con, expected_rows, expected_columns, "gold.divergence_panel")
        con.execute("COMMIT")
    except BaseException:
        try:
            con.execute("ROLLBACK")
        except duckdb.Error:
            # Commit can fail or return an ambiguous response after closing the transaction.
            pass
        raise
    verify_panel(con, expected_rows, expected_columns, "gold.divergence_panel")
    return published_at


def verify_panel(con, expected_rows, expected_columns, relation):
    if count(con, relation) != expected_rows or describe(con, relation) != expected_columns:
        raise RuntimeError(f"{relation} differs from the gold Parquet row count or column order")


def archive_files(client, gold, run_id):
    hashes = {}
    for filename in FILES:
        key = f"gold/runs/{run_id}/{filename}"
        data = (gold / filename).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        try:
            client.put_object(
                Bucket=BUCKET, Key=key, Body=data, IfNoneMatch="*", Metadata={"sha256": digest},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] not in ("412", "PreconditionFailed"):
                raise
            if client.head_object(Bucket=BUCKET, Key=key)["Metadata"].get("sha256") != digest:
                raise RuntimeError(f"Run {run_id} already contains different bytes for {filename}") from error
        hashes[filename] = digest
    return hashes


def advance_latest(client, run_id, published_at, hashes):
    for filename in FILES:
        client.copy_object(
            Bucket=BUCKET, Key=f"gold/latest/{filename}",
            CopySource={"Bucket": BUCKET, "Key": f"gold/runs/{run_id}/{filename}"},
        )
    client.put_object(
        Bucket=BUCKET, Key="gold/latest/manifest.json",
        Body=json.dumps({
            "run_id": run_id, "published_at": published_at.isoformat(),
            "files": {
                filename: {"key": f"gold/runs/{run_id}/{filename}", "sha256": hashes[filename]}
                for filename in FILES
            },
        }).encode(), ContentType="application/json",
    )


def publish(*, dry_run=False):
    database = os.getenv("MOTHERDUCK_DATABASE", "divergence_index")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database):
        raise ValueError("MOTHERDUCK_DATABASE must be a SQL identifier")
    if dry_run:
        print(f"MotherDuck destination md:{database}")
        for target, source in {**TABLES, **DOCUMENTS}.items():
            print(f"Replace {target} from {source}")
        print("Append meta.publish_log")
        for filename in FILES:
            print(f"S3 stage gold/runs/<run_id>/{filename}; refresh gold/latest/{filename}")
        print("S3 advance gold/latest/manifest.json")
        return

    if not os.getenv("MOTHERDUCK_TOKEN"):
        raise RuntimeError("MOTHERDUCK_TOKEN is required")
    gold = Path(os.getenv("DIVERGENCE_GOLD_DIR", GOLD))
    warehouse = Path(os.getenv("DUCKDB_PATH", WAREHOUSE))
    metadata = json.loads((gold / DOCUMENTS["meta.pipeline_metadata"]).read_text())
    if metadata["run_status"] != "success" or metadata["validation"]["checks_failed"]:
        raise RuntimeError("A successful gold export is required")
    run_id = metadata["run_id"]
    if not re.fullmatch(r"[A-Za-z0-9_:\-]+", run_id):
        raise ValueError("Invalid publish run id")

    client = s3_client()
    hashes = archive_files(client, gold, run_id)
    with duckdb.connect(f"md:{database}") as con:
        published_at = remote_publish(con, warehouse, gold, metadata, run_id, dt.datetime.now(dt.UTC))
    advance_latest(client, run_id, published_at, hashes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    publish(**vars(parser.parse_args()))
