"""Bronze ingestion: run the Airbyte declarative SDMX connectors via PyAirbyte.

    uv run python pipeline/ingest/run_ingest.py            # all sources
    uv run python pipeline/ingest/run_ingest.py --source bis

Each run writes an immutable, dated snapshot per stream:

    data/bronze/<stream>/vintage=<YYYY-MM-DD>/data.parquet
    data/bronze/_runs/<YYYY-MM-DD>.json      (row counts + per-country coverage)
    data/warehouse.duckdb  -> bronze.<stream>   (all vintages, via load_bronze.py)

No transformation happens here: values stay as the source published them
(strings, original dimension codes, full `raw` row). Typing, frequency
alignment and everything in the methodology belong to the silver layer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")  # disable PyAirbyte telemetry

import airbyte as ab  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

if __package__:
    from .load_bronze import load as load_bronze_into_duckdb
    from .s3_writer import BRONZE_ROOT, write_bronze
else:
    from load_bronze import load as load_bronze_into_duckdb
    from s3_writer import BRONZE_ROOT, write_bronze

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = Path(__file__).parent / "airbyte" / "manifests"
BRONZE = ROOT / "data" / "bronze"
CONFIG = ROOT / "pipeline" / "config.yaml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def sources(cfg: dict) -> dict[str, dict]:
    countries = cfg["countries"]
    return {
        "oecd": {
            "manifest": MANIFESTS / "source_oecd_sdmx.yaml",
            "config": {"countries": [c["iso3"] for c in countries], "start_period": cfg["start_period"]},
        },
        "bis": {
            "manifest": MANIFESTS / "source_bis_sdmx.yaml",
            "config": {"countries": [c["iso2"] for c in countries], "start_period": cfg["start_period"]},
        },
    }


def coverage(df: pd.DataFrame) -> dict:
    out = {}
    for (area, freq), g in df.groupby(["ref_area", "freq"]):
        periods = g["time_period"].dropna()
        out.setdefault(area, {})[freq] = {
            "rows": int(len(g)),
            "first": str(periods.min()),
            "last": str(periods.max()),
        }
    return out


def read_streams(selected, cache_dir, fixture_vintage=None):
    cfg = load_config()
    cache = None if fixture_vintage else ab.new_local_cache(cache_name="bronze", cache_dir=cache_dir)
    for name, src in sources(cfg).items():
        if selected and name not in selected:
            continue
        manifest = yaml.safe_load(src["manifest"].read_text())
        stream_names = [entry["name"] for entry in manifest["streams"]]
        if fixture_vintage:
            for stream in stream_names:
                path = BRONZE / stream / f"vintage={fixture_vintage}" / "data.parquet"
                yield name, stream, pd.read_parquet(path)
            continue
        source = ab.get_source(f"source-{name}-sdmx", config=src["config"], source_manifest=manifest)
        source.check()
        source.select_all_streams()
        result = source.read(cache=cache, force_full_refresh=True, write_strategy="replace")
        if set(result.streams) != set(stream_names):
            raise RuntimeError(f"Incomplete {name} read: {result.streams}")
        for stream in stream_names:
            df = result[stream].to_pandas()
            df = df.drop(columns=[c for c in df.columns if c.startswith("_airbyte")])
            if "raw" in df.columns:
                df["raw"] = df["raw"].map(lambda v: v if isinstance(v, str) else json.dumps(v))
            yield name, stream, df


def run(selected: list[str], *, dest="local", s3_root=BRONZE_ROOT, fixture_vintage=None) -> dict:
    started_at = dt.datetime.now(dt.UTC)
    if fixture_vintage and (dest != "s3" or s3_root.startswith("s3://")):
        raise ValueError("Fixture replay requires a local S3-layout mirror")
    if dest == "s3":
        with tempfile.TemporaryDirectory() as cache_dir:
            streams = list(read_streams(selected, Path(cache_dir), fixture_vintage))
        write_bronze(s3_root, streams, started_at)
        print(f"  {len(streams)} streams written to {s3_root}")
        return {stream: len(df) for _, stream, df in streams}

    vintage = dt.date.today().isoformat()
    report: dict = {"vintage": vintage, "started_at": started_at.isoformat(), "streams": {}}
    for name, stream, df in read_streams(selected, BRONZE / "_airbyte_cache"):
        out = BRONZE / stream / f"vintage={vintage}" / "data.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)
        report["streams"][stream] = {
            "source": name,
            "rows": int(len(df)),
            "path": str(out.relative_to(ROOT)),
            "coverage": coverage(df),
        }
        print(f"  {stream:36s} {len(df):>6d} rows -> {out.relative_to(ROOT)}")

    report["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
    runs = BRONZE / "_runs"
    runs.mkdir(parents=True, exist_ok=True)
    run_file = runs / f"{vintage}.json"
    if run_file.exists():  # a partial run (--source) on the same day merges, never drops streams
        previous = json.loads(run_file.read_text())
        report["streams"] = {**previous.get("streams", {}), **report["streams"]}
        report["started_at"] = previous.get("started_at", report["started_at"])
    run_file.write_text(json.dumps(report, indent=2))

    # Rebuild the DuckDB bronze schema from all Parquet vintages (dbt reads from here).
    load_bronze_into_duckdb()
    print("  bronze.* tables refreshed in data/warehouse.duckdb")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", action="append", choices=["oecd", "bis"], default=[])
    p.add_argument("--dest", choices=["local", "s3"], default="local")
    p.add_argument("--s3-root", default=BRONZE_ROOT)
    p.add_argument("--fixture-vintage", type=dt.date.fromisoformat)
    args = p.parse_args()
    run(args.source, dest=args.dest, s3_root=args.s3_root, fixture_vintage=args.fixture_vintage)
