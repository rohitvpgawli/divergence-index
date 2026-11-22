import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq
import pytest
from botocore.exceptions import ClientError

from pipeline.ingest import s3_writer
from pipeline.publish import export_gold, publish_motherduck

ROOT = Path(__file__).resolve().parents[1]
START = dt.datetime.fromtimestamp(1795369809.600, dt.UTC)


@pytest.fixture
def streams():
    data = {column: ["abc", None] for column in s3_writer.COLUMNS}
    data["raw"] = [{"OBS_VALUE": "1"}, {"OBS_VALUE": "2"}]
    frame = pd.DataFrame(data)
    return [("oecd", "k4_cpi_components", frame), ("bis", "k2_household_dsr", frame)]


def test_s3_mirror_parts_and_sync_id(tmp_path, streams):
    s3_writer.write_bronze(str(tmp_path), streams, START, part_rows=1)
    macro = (ROOT / "pipeline/transform/macros/stg_sdmx.sql").read_text()
    regex = re.search(r"regexp_extract\(filename, '([^']+)'", macro)[1]
    keys = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*.parquet"))
    assert keys == [
        f"{source}/{stream}/2026_11_22_1795369809600_{part}.parquet"
        for source, stream, _ in sorted(streams)
        for part in range(2)
    ]
    assert {re.search(regex, key)[1] for key in keys} == {"1795369809600"}
    table = pq.read_table(tmp_path / keys[0])
    assert table.schema == s3_writer.SCHEMA
    assert json.loads(table["raw"][0].as_py()) == {"OBS_VALUE": "1"}


class FakeS3:
    def __init__(self, fail_on):
        self.fail_on = fail_on
        self.uploads = 0
        self.copies = 0
        self.objects = {"airbyte/bis/old.parquet": {}}

    def list_objects_v2(self, **kwargs):
        return {"KeyCount": 0}

    def upload_file(self, path, bucket, key):
        self.uploads += 1
        if self.fail_on == "upload" and self.uploads == 2:
            raise OSError("upload failed")
        self.objects[key] = {}

    def put_object(self, *, Key, **kwargs):
        self.objects[Key] = {}

    def copy_object(self, *, Key, CopySource, Metadata, IfNoneMatch, **kwargs):
        assert CopySource["Key"] in self.objects
        assert IfNoneMatch == "*"
        self.objects[Key] = Metadata
        self.copies += 1
        if self.fail_on == "copy" and self.copies == 2:
            raise OSError("copy failed after writing the final key")

    def head_object(self, *, Key, **kwargs):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"Metadata": self.objects[Key]}

    def delete_object(self, *, Key, **kwargs):
        self.objects.pop(Key, None)


@pytest.mark.parametrize("failure", ["upload", "copy"])
def test_failed_upload_leaves_no_final_keys(streams, failure):
    client = FakeS3(failure)
    with pytest.raises(OSError):
        s3_writer.write_bronze("s3://example/airbyte", streams, START, part_rows=1, client=client)
    assert {key for key in client.objects if "/_staging/" not in key} == {"airbyte/bis/old.parquet"}


def test_export_uses_dbt_run_results_override(tmp_path, monkeypatch):
    artifact = tmp_path / "run_results.json"
    monkeypatch.setenv("DBT_RUN_RESULTS", str(artifact))
    artifact.write_text(json.dumps({"results": [
        {"unique_id": "model.divergence_index.gld_divergence_panel", "status": "success"},
        {"unique_id": "test.divergence_index.z_extreme_values_warn", "status": "warn"},
    ]}))
    assert export_gold.dbt_validation()["checks_run"] == 1
    artifact.write_text(json.dumps({"results": [
        {"unique_id": "model.divergence_index.gld_divergence_panel", "status": "success"},
        {"unique_id": "test.divergence_index.contract", "status": "fail"},
    ]}))
    with pytest.raises(SystemExit):
        export_gold.dbt_validation()


def test_publish_cli_dry_run_lists_exact_tables():
    plan = subprocess.check_output(
        [sys.executable, "pipeline/publish/publish_motherduck.py", "--dry-run"],
        cwd=ROOT, text=True,
    )
    assert re.findall(r"^(?:Replace|Append) (\S+)", plan, re.M) == [
        "gold.divergence_panel", "gold.indicator_scores", "gold.baseline_stats",
        "reference.dim_indicator", "reference.countries", "silver.indicator_quarterly",
        "meta.pipeline_metadata", "meta.component_contributions", "meta.publish_log",
    ]


def test_publish_swaps_and_rolls_back_on_log_failure(tmp_path):
    local = tmp_path / "warehouse.duckdb"
    gold = tmp_path / "gold"
    gold.mkdir()
    for name in publish_motherduck.DOCUMENTS.values():
        (gold / name).write_text("{}")
    with duckdb.connect(str(local)) as con:
        for schema in ("gold", "reference", "silver"):
            con.execute(f"CREATE SCHEMA {schema}")
        for table in publish_motherduck.TABLES.values():
            con.execute(f"CREATE TABLE {table} AS SELECT 42 AS id")
        con.execute(f"COPY gold.gld_divergence_panel TO '{gold / 'divergence_panel.parquet'}'")

    metadata = {"git_commit": "sha", "latest_complete_common_quarter": "2021-Q2"}
    with duckdb.connect() as target:
        publish_motherduck.remote_publish(target, local, gold, metadata, "first", START)
        assert target.execute("SELECT id FROM gold.divergence_panel").fetchone() == (42,)
        assert target.execute("SELECT run_id FROM meta.publish_log").fetchall() == [("first",)]
        with duckdb.connect(str(local)) as con:
            con.execute("UPDATE gold.gld_divergence_panel SET id=43")
            con.execute("UPDATE gold.gld_indicator_scores SET id=43")
            con.execute(f"COPY gold.gld_divergence_panel TO '{gold / 'divergence_panel.parquet'}'")
        with pytest.raises(KeyError, match="git_commit"):
            publish_motherduck.remote_publish(target, local, gold, {}, "second", START)
        assert target.execute("SELECT id FROM gold.divergence_panel").fetchone() == (42,)
        assert target.execute("SELECT id FROM gold.indicator_scores").fetchone() == (42,)
        assert target.execute("SELECT run_id FROM meta.publish_log").fetchall() == [("first",)]
