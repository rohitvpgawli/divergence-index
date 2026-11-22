"""Write Airbyte-compatible bronze Parquet without replacing previous syncs."""

import datetime as dt
import json
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

REGION = "ap-south-1"
BUCKET = "divergence-index-data-lqpeej"
BRONZE_ROOT = f"s3://{BUCKET}/airbyte"
COLUMNS = (
    "source", "indicator_id", "dataflow", "ref_area", "freq", "time_period",
    "obs_value", "obs_status", "unit_measure", "series_variant", "raw",
)
SCHEMA = pa.schema([
    *((column, pa.string()) for column in COLUMNS),
    ("_airbyte_raw_id", pa.string()),
    ("_airbyte_extracted_at", pa.timestamp("us", tz="UTC")),
])


def s3_client():
    profile = None
    if os.getenv("DIVERGENCE_AWS_CHAIN", "config") == "config":
        profile = os.getenv("DIVERGENCE_AWS_PROFILE", "divergence-reader")
    return boto3.Session(profile_name=profile, region_name=REGION).client("s3")


def bronze_key(source, stream, started_at, part):
    started_at = started_at.astimezone(dt.UTC)
    sync_id = (started_at - dt.datetime(1970, 1, 1, tzinfo=dt.UTC)) // dt.timedelta(milliseconds=1)
    return f"{source}/{stream}/{started_at:%Y_%m_%d}_{sync_id:013d}_{part}.parquet"


def _table(frame, started_at):
    raw = frame["raw"].map(lambda value: value if isinstance(value, str) else json.dumps(value))
    columns = {name: frame[name].astype("string") for name in COLUMNS}
    columns["raw"] = raw
    columns["_airbyte_raw_id"] = [str(uuid.uuid4()) for _ in range(len(frame))]
    columns["_airbyte_extracted_at"] = [started_at] * len(frame)
    return pa.Table.from_pydict(columns, schema=SCHEMA)


def write_bronze(root, streams, started_at, *, part_rows=10_000, client=None):
    """Write a complete set of streams. Each entry is (source, stream, frame)."""
    remote = root.startswith("s3://")
    uri = urlsplit(root)
    prefix = uri.path.strip("/")
    local_root = Path(root)
    if not remote:
        local_root.mkdir(parents=True, exist_ok=True)
    batch = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(dir=None if remote else local_root) as scratch:
        files = {}
        for source, stream, frame in streams:
            if not len(frame):
                raise ValueError(f"Empty bronze stream: {source}/{stream}")
            for part, offset in enumerate(range(0, len(frame), part_rows)):
                key = bronze_key(source, stream, started_at, part)
                path = Path(scratch) / key
                path.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(_table(frame.iloc[offset:offset + part_rows], started_at), path)
                files[key] = path
        if not files:
            raise ValueError("No bronze streams to publish")
        if remote:
            _publish_s3(client or s3_client(), uri.netloc, prefix, batch, files)
        else:
            promoted = []
            try:
                for key, path in files.items():
                    target = local_root / key
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.link(path, target)
                    promoted.append(target)
            except BaseException:
                for target in promoted:
                    target.unlink()
                raise


def _publish_s3(client, bucket, prefix, batch, files):
    pending = f"{prefix}/_pending/"
    if client.list_objects_v2(Bucket=bucket, Prefix=pending, MaxKeys=1).get("KeyCount"):
        raise RuntimeError(f"Resolve interrupted bronze promotion under s3://{bucket}/{pending} first")

    # Stage every part outside the stream globs before exposing any final key.
    staging = f"{prefix}/_staging/{batch}"
    for key, path in files.items():
        client.upload_file(str(path), bucket, f"{staging}/{key}")

    journal = f"{pending}{batch}.json"
    final_keys = {key: f"{prefix}/{key}" for key in files}
    client.put_object(Bucket=bucket, Key=journal, Body=json.dumps({
        "staging": staging, "keys": list(final_keys.values()),
    }).encode())
    attempted = []
    try:
        for key, final in final_keys.items():
            attempted.append(final)
            client.copy_object(
                Bucket=bucket, Key=final, CopySource={"Bucket": bucket, "Key": f"{staging}/{key}"},
                IfNoneMatch="*", MetadataDirective="REPLACE", Metadata={"bronze-batch": batch},
            )
    except BaseException:
        # An ambiguous copy response may represent a successful write.
        # Check ownership before removing any new part.
        for key in attempted:
            try:
                info = client.head_object(Bucket=bucket, Key=key)
            except ClientError as error:
                if error.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                    continue
                raise
            if info["Metadata"].get("bronze-batch") == batch:
                client.delete_object(Bucket=bucket, Key=key)
        client.delete_object(Bucket=bucket, Key=journal)
        raise
    client.delete_object(Bucket=bucket, Key=journal)
