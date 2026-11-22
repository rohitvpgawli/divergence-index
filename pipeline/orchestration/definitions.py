"""Monthly refresh. Operations keep the dbt build and its contract tests together."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from dagster import (
    DefaultScheduleStatus, DefaultSensorStatus, Definitions, RunFailureSensorContext,
    ScheduleDefinition, job, op, run_failure_sensor,
)
from dagster_dbt import DbtCliResource

from pipeline.ingest.run_ingest import run
from pipeline.ingest.s3_writer import BRONZE_ROOT

ROOT = Path(__file__).resolve().parents[2]
TRANSFORM = ROOT / "pipeline" / "transform"


def warehouse_path():
    return Path(os.getenv("DUCKDB_PATH", ROOT / "data" / "warehouse.duckdb")).resolve()


def gold_path(instance, run_id):
    return Path(instance.storage_directory()) / run_id / "gold"


@op
def ingest() -> str:
    bronze_root = os.getenv("DIVERGENCE_BRONZE_ROOT", BRONZE_ROOT)
    if not bronze_root.startswith("s3://"):
        bronze_root = str(Path(bronze_root).resolve())
    run([], dest="s3", s3_root=bronze_root, fixture_vintage=os.getenv("DIVERGENCE_FIXTURE_VINTAGE"))
    return bronze_root


@op
def build(context, bronze_root: str, dbt: DbtCliResource) -> str:
    os.environ["DUCKDB_PATH"] = str(warehouse_path())
    args = ["build", "--vars", json.dumps({"bronze_source": "s3", "s3_bronze_root": bronze_root})]
    if not bronze_root.startswith("s3://"):
        args += ["--target", "offline"]
    target = Path(context.instance.storage_directory()) / context.run_id / "dbt"
    target.mkdir(parents=True, exist_ok=True)
    invocation = dbt.cli(args, target_path=target)
    invocation.wait()
    return str(invocation.target_path / "run_results.json")


@op
def export(context, run_results: str) -> str:
    gold = gold_path(context.instance, context.run_id)
    subprocess.run(
        [sys.executable, "-m", "pipeline.publish.export_gold"], cwd=ROOT, check=True,
        env={**os.environ, "DBT_RUN_RESULTS": run_results, "DUCKDB_PATH": str(warehouse_path()),
             "DIVERGENCE_GOLD_DIR": str(gold)},
    )
    return str(gold)


@op
def publish(gold: str):
    args = []
    if os.getenv("DIVERGENCE_PUBLISH_DRY_RUN") == "1":
        args.append("--dry-run")
    elif not os.getenv("DIVERGENCE_BRONZE_ROOT", BRONZE_ROOT).startswith("s3://"):
        raise ValueError("Publishing from a local mirror requires DIVERGENCE_PUBLISH_DRY_RUN=1")
    subprocess.run(
        [sys.executable, "-m", "pipeline.publish.publish_motherduck", *args], cwd=ROOT, check=True,
        env={**os.environ, "DUCKDB_PATH": str(warehouse_path()), "DIVERGENCE_GOLD_DIR": gold},
    )


@job
def monthly_refresh():
    publish(export(build(ingest())))


monthly_schedule = ScheduleDefinition(
    job=monthly_refresh, cron_schedule="0 6 15 * *", execution_timezone="UTC",
    default_status=DefaultScheduleStatus.RUNNING,
)


@run_failure_sensor(monitored_jobs=[monthly_refresh], default_status=DefaultSensorStatus.RUNNING)
def alert_run_failure(context: RunFailureSensorContext):
    steps = sorted({event.step_key for event in context.get_step_failure_events() if event.step_key})
    run = context.dagster_run
    text = f"{run.job_name} failed | step: {', '.join(steps) or 'unknown'} | run: {run.run_id}"
    context.log.warning(text)
    if url := os.getenv("ALERT_WEBHOOK_URL"):
        request = Request(url, data=json.dumps({"text": text}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=10):
                pass
        except Exception:
            # Avoid logging the URL or propagating it in a request exception.
            raise RuntimeError("Failure alert delivery failed") from None


defs = Definitions(
    jobs=[monthly_refresh], schedules=[monthly_schedule], sensors=[alert_run_failure],
    resources={"dbt": DbtCliResource(project_dir=TRANSFORM, profiles_dir=TRANSFORM,
                                    dbt_executable=str(Path(sys.executable).with_name("dbt")))},
)
