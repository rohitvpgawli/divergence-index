"""Publish Gold: dbt tables -> the four contract files in data/gold/.

    uv run python pipeline/publish/export_gold.py

Runs AFTER `dbt build`. It refuses to publish unless that build finished with
zero errors (contract §0.4: fail loudly, never overwrite the last good Gold).

Writes, in the same shapes as data/gold_mock/ (so the dashboard only swaps folders):
    divergence_panel.parquet   canonical; file metadata divergence.schema_version
    divergence_panel.csv       same DataFrame, full precision (%.17g)
    component_contributions.json
    pipeline_metadata.json

Then checks contract Q8 (Parquet == CSV after reload) and Q9 (both JSON files
validate against docs/schemas/*.schema.json). Files are written to a staging
folder first and only moved into data/gold/ when every check passes.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import jsonschema
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
GOLD = ROOT / "data" / "gold"
SCHEMAS = ROOT / "docs" / "schemas"
RUN_RESULTS = ROOT / "pipeline" / "transform" / "target" / "run_results.json"

SCHEMA_VERSION = "1.0.0-draft"      # tracks docs/DATA_CONTRACT.md
SHARE_THRESHOLD = 0.25              # contract §4 / D6
HERO_START = "2015-Q1"              # contract §4: contributions JSON starts here
NATIVE_FREQUENCY = {"H1": "Q", "H2": "M", "H3": "M", "K1": "Q", "K2": "Q", "K3": "Q", "K4": "M (AUS: Q)"}
SOURCE_BASE_YEAR = {"K3": None, "K4": 2015}


def fail(msg: str) -> None:
    print(f"PUBLISH ABORTED: {msg}\nGold in data/gold/ was NOT changed.", file=sys.stderr)
    sys.exit(1)


def dbt_validation() -> dict:
    """Summarise the last dbt run; refuse to publish after a failed build."""
    run_results = Path(os.environ.get("DBT_RUN_RESULTS", RUN_RESULTS))
    if not run_results.exists():
        fail("no dbt run_results.json found. Run `dbt build` first.")
    results = json.loads(run_results.read_text())["results"]
    tests = [r for r in results if r["unique_id"].startswith(("test.", "unit_test."))]
    bad = [r for r in results if r["status"] in ("error", "fail", "runtime error")]
    if bad:
        fail(f"last dbt build had {len(bad)} failing node(s), e.g. {bad[0]['unique_id']}")
    if not any(r["unique_id"].endswith("gld_divergence_panel") for r in results):
        fail("last dbt run did not build gld_divergence_panel. Run a full `dbt build`.")
    warnings = [{"check": r["unique_id"].split(".")[-1], "failures": r.get("failures"), "message": r.get("message")}
                for r in tests if r["status"] == "warn"]
    return {"checks_run": len(tests), "checks_failed": 0, "warnings": warnings, "revision_alerts": []}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def build_contributions(panel: pd.DataFrame, dims: pd.DataFrame, common_q: str) -> dict:
    ids = list(dims["indicator_id"])
    rows = panel[panel["is_composite_eligible"] & (panel["quarter"] >= HERO_START)]
    countries: dict = {}
    for r in rows.itertuples(index=False):
        contrib = {i: float(getattr(r, f"contrib_{i.lower()}_z")) for i in ids}
        gap = float(r.divergence_gap_z)
        ok = abs(gap) >= SHARE_THRESHOLD
        countries.setdefault(r.country_iso, {})[r.quarter] = {
            "divergence_gap_z": gap,
            "headline_z": float(r.headline_z),
            "kitchen_table_z": float(r.kitchen_table_z),
            "contributions": contrib,
            "shares": {i: v / gap for i, v in contrib.items()} if ok else None,
            "shares_suppressed": not ok,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "model": "z",
        "latest_complete_common_quarter": common_q,
        "components": [
            {"id": d.indicator_id, "label": d.label, "basket": d.basket,
             "weight": round(1 / 3 if d.basket == "headline" else 1 / 4, 4), "sign_in_gap": int(d.sign_in_gap)}
            for d in dims.itertuples(index=False)
        ],
        "countries": countries,
    }


def build_metadata(con, panel, dims, validation, common_q, run_ts) -> dict:
    latest_by_country = (panel[panel["is_complete"]].groupby("country_iso")["quarter"].max()
                         .reindex(sorted(panel["country_iso"].unique())))
    latest_obs = con.sql("""
        select indicator_id, country_iso, arg_max(source_series, quarter_start_date) as series,
               arg_max(sa_status, quarter_start_date) as sa, cast(max(vintage) as varchar) as vintage
        from gold.gld_indicator_scores where raw is not null group by 1, 2
    """).df()
    stats = con.sql("select * from gold.gld_baseline_stats").df()
    indicators = {}
    for d in dims.itertuples(index=False):
        li = latest_obs[latest_obs.indicator_id == d.indicator_id].set_index("country_iso")
        st = stats[stats.indicator_id == d.indicator_id].set_index("country_iso")
        z_stats = {}
        for c, s in st.iterrows():
            entry = {"mean": None if pd.isna(s["mean"]) else float(s["mean"]), "sd": float(s["sigma"]),
                     "n_quarters": int(s["n_quarters"])}
            if s["treatment"] == "detrended":   # sd is the residual SD around ln-linear trend
                entry.update({"trend_alpha": float(s["trend_alpha"]), "trend_beta": float(s["trend_beta"]),
                              "scale": "ln(value) residual vs 2010-19 log-linear trend"})
            z_stats[c] = entry
        indicators[d.indicator_id] = {
            "label": d.label,
            "source": d.source,
            "dataset": d.dataset,
            "series_keys": li["series"].to_dict(),
            "native_frequency": NATIVE_FREQUENCY[d.indicator_id],
            "unit": d.unit,
            "sa_status": li["sa"].to_dict(),
            "source_base_year": SOURCE_BASE_YEAR.get(d.indicator_id),
            "vintage_date": li["vintage"].to_dict(),
            "treatment": d.treatment,
            "z_baseline_stats": z_stats,
            "baseline_window_override": {},
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"{run_ts}_{git_commit()}",
        "run_timestamp_utc": run_ts,
        "git_commit": git_commit(),
        "run_status": "success",
        "latest_published_quarter": str(panel["quarter"].max()),
        "latest_complete_common_quarter": common_q,
        "latest_complete_quarter_by_country": {c: (None if pd.isna(q) else q) for c, q in latest_by_country.items()},
        "baseline": {"z_window": ["2010-Q1", "2019-Q4"], "idx100_anchor": "2019-Q4"},
        "indicators": indicators,
        "validation": validation,
    }


def write_panel(panel: pd.DataFrame, out: Path) -> None:
    table = pa.Table.from_pandas(panel, preserve_index=False)
    meta = {**(table.schema.metadata or {}), b"divergence.schema_version": SCHEMA_VERSION.encode()}
    pq.write_table(table.replace_schema_metadata(meta), out / "divergence_panel.parquet")
    panel.to_csv(out / "divergence_panel.csv", index=False, float_format="%.17g")


def check_q8(out: Path) -> None:
    pqf = pd.read_parquet(out / "divergence_panel.parquet")
    # float_precision="round_trip": exact parse of the %.17g values (default parser can be 1 ulp off)
    csv = pd.read_csv(out / "divergence_panel.csv", float_precision="round_trip", dtype={c: pqf[c].dtype for c in pqf.columns if pqf[c].dtype != "object"})
    csv["quarter_start_date"] = pd.to_datetime(csv["quarter_start_date"]).dt.date
    if list(csv.columns) != list(pqf.columns):
        fail("Q8: CSV and Parquet columns differ")
    try:
        pd.testing.assert_frame_equal(pqf, csv, check_exact=True, check_dtype=False)
    except AssertionError as e:
        fail(f"Q8: Parquet and CSV differ after reload: {str(e)[:300]}")
    if pq.ParquetFile(out / "divergence_panel.parquet").schema_arrow.metadata.get(b"divergence.schema_version") != SCHEMA_VERSION.encode():
        fail("Q8: Parquet is missing divergence.schema_version metadata")


def check_q9(out: Path) -> None:
    for name in ("component_contributions", "pipeline_metadata"):
        schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
        doc = json.loads((out / f"{name}.json").read_text())
        try:
            jsonschema.validate(doc, schema)
        except jsonschema.ValidationError as e:
            fail(f"Q9: {name}.json does not match its JSON Schema: {e.message} at {list(e.absolute_path)}")


def main() -> None:
    validation = dbt_validation()
    warehouse = Path(os.environ.get("DUCKDB_PATH", WAREHOUSE))
    gold = Path(os.environ.get("DIVERGENCE_GOLD_DIR", GOLD)).resolve()
    run_ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with duckdb.connect(str(warehouse), read_only=True) as con:
        panel = con.sql("select * from gold.gld_divergence_panel order by country_iso, quarter").df()
        dims = con.sql("select * from reference.dim_indicator order by ordinal").df()
        eligible = panel[panel["is_composite_eligible"]]
        if eligible.empty:
            fail("no composite-eligible quarter. latest_complete_common_quarter is undefined.")
        common_q = str(eligible["quarter"].max())
        panel["quarter_start_date"] = pd.to_datetime(panel["quarter_start_date"]).dt.date
        panel["n_components_available"] = panel["n_components_available"].astype("int64")
        contributions = build_contributions(panel, dims, common_q)
        metadata = build_metadata(con, panel, dims, validation, common_q, run_ts)

    staging = gold.parent / f".gold_staging_{run_ts.replace(':', '')}"
    staging.mkdir(parents=True)
    try:
        write_panel(panel, staging)
        (staging / "component_contributions.json").write_text(json.dumps(contributions, indent=2))
        (staging / "pipeline_metadata.json").write_text(json.dumps(metadata, indent=2))
        check_q8(staging)
        check_q9(staging)
        gold.mkdir(parents=True, exist_ok=True)
        for f in staging.iterdir():          # every check passed: swap the files in
            shutil.move(str(f), gold / f.name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    print(f"Gold published to {gold}/  (schema {SCHEMA_VERSION})")
    print(f"  divergence_panel: {len(panel)} rows x {panel.shape[1]} columns, "
          f"latest published {metadata['latest_published_quarter']}, latest complete common {common_q}")
    print(f"  checks: {validation['checks_run']} dbt tests passed, {len(validation['warnings'])} warning(s); Q8 + Q9 passed")


if __name__ == "__main__":
    main()
