# Deploy the monthly Divergence Index refresh

Run the AWS commands from a workstation with AWS CLI v2, an authenticated AWS session, and the Session Manager plugin. The operator needs permission to create and pass the instance role, provision EC2, write the SSM parameters, and start SSM sessions. The existing bucket is `divergence-index-data-lqpeej` in `ap-south-1`.

## 1. Instance role and profile

Run these commands from the repository root.

```bash
export AWS_REGION=ap-south-1 AWS_DEFAULT_REGION=ap-south-1
ROLE=divergence-ec2
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws iam create-role --role-name "$ROLE" \
  --assume-role-policy-document file://infra/aws/ec2-trust-policy.json
POLICY_FILE=$(mktemp)
sed "s/<ACCOUNT_ID>/$ACCOUNT_ID/g" infra/aws/ec2-pipeline-role-policy.json > "$POLICY_FILE"
aws iam put-role-policy --role-name "$ROLE" --policy-name divergence-pipeline \
  --policy-document "file://$POLICY_FILE"
rm "$POLICY_FILE"
aws iam attach-role-policy --role-name "$ROLE" \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name "$ROLE"
aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
```

The role reads and writes the Airbyte and gold prefixes, deletes only Airbyte objects during writer rollback or staging cleanup, and reads the pipeline's SecureString parameters. The application verifies the batch owner before deleting any promoted bronze part.

## 2. SecureString parameters and MotherDuck

Create the `divergence_index` database in MotherDuck and create a write-capable access token for an account with permission to manage its tables. Use the optional Slack-compatible webhook parameter for failure alerts. The function sends each value through stdin so it stays out of shell history and the AWS CLI's command arguments.

```bash
put_pipeline_secret() {
  local secret
  read -r -s -p "Value for $1: " secret
  printf '\n'
  printf '%s' "$secret" | python3 -c 'import json,sys; json.dump({
    "Name": sys.argv[1], "Type": "SecureString", "KeyId": "alias/aws/ssm",
    "Value": sys.stdin.read(), "Overwrite": True
  }, sys.stdout)' "$1" | aws ssm put-parameter --cli-input-json file:///dev/stdin
}
put_pipeline_secret /divergence/motherduck_token
# Optional
put_pipeline_secret /divergence/alert_webhook_url
```

## 3. Instance and network

Use an existing VPC and a public subnet with an internet gateway. This example uses a public IP for outbound access and a new security group with zero inbound rules. A private subnet with outbound NAT also works. The instance needs outbound HTTPS for SSM, S3, package downloads, the SDMX APIs, and MotherDuck.

```bash
aws ec2 describe-subnets \
  --query 'Subnets[].[SubnetId,VpcId,AvailabilityZone,MapPublicIpOnLaunch]' --output table
read -r -p 'Public subnet ID: ' SUBNET_ID
VPC_ID=$(aws ec2 describe-subnets --subnet-ids "$SUBNET_ID" --query 'Subnets[0].VpcId' --output text)
SG_ID=$(aws ec2 create-security-group --vpc-id "$VPC_ID" --group-name divergence-ec2 \
  --description 'Divergence EC2 with Session Manager access' --query GroupId --output text)
AMI_ID=$(aws ssm get-parameter \
  --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query Parameter.Value --output text)
INSTANCE_ID=$(aws ec2 run-instances --image-id "$AMI_ID" --instance-type t3.medium \
  --iam-instance-profile Name="$ROLE" \
  --network-interfaces "DeviceIndex=0,SubnetId=$SUBNET_ID,Groups=$SG_ID,AssociatePublicIpAddress=true" \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}' \
  --metadata-options HttpTokens=required,HttpEndpoint=enabled \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=divergence-ec2}]' \
  --query 'Instances[0].InstanceId' --output text)
aws ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID"
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" --query 'InstanceInformationList[0].PingStatus'
```

Wait for SSM to report `Online`. If the instance profile was just created and EC2 reports it as invalid, retry launch once IAM has propagated.

## 4. Bootstrap and operate

Disable any existing Airbyte OSS schedule for these streams before enabling this deployment. The GitHub workflow is manual only. Open a Session Manager shell.

```bash
aws ssm start-session --target "$INSTANCE_ID"
```

On EC2, use `main` after merge or `deploy/ec2-dagster` for a branch deployment.

```bash
REF=main
curl -fsSL "https://raw.githubusercontent.com/rohitvpgawli/divergence-index/$REF/infra/ec2/bootstrap.sh" \
  -o /tmp/divergence-bootstrap.sh
sudo bash /tmp/divergence-bootstrap.sh "$REF"
sudo systemctl status dagster-daemon dagster-webserver --no-pager
sudo journalctl -u dagster-daemon -u dagster-webserver -n 100 --no-pager
```

Start the port forward from the workstation.

```bash
aws ssm start-session --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["3000"],"localPortNumber":["3000"]}'
```

Open `http://127.0.0.1:3000`, select **Jobs → monthly_refresh → Launchpad**, and launch with the default config. Confirm that ingest, build, export, and publish succeeded. Check the schedule and failure sensor under **Automation**. The schedule uses `0 6 15 * *` in UTC. The expected `z_extreme_values_warn` warning allows processing to continue. The dbt profile uses one thread for both dbt and DuckDB and disables two cost-based join reorderings to keep floating-point output stable across first builds and rebuilds.

The service account reads the installed checkout and writes state under `/var/lib/divergence`. Each run stores its dbt artifacts and checked gold files in its Dagster run directory. The root-owned checkout has push disabled. Wait for active runs to finish before deploying or reloading rotated secrets.

```bash
sudo bash /opt/divergence-index/infra/ec2/deploy.sh
# For a secret rotation with the same code
sudo systemctl restart dagster-daemon dagster-webserver
sudo journalctl -u dagster-daemon -u dagster-webserver -f
```

## 5. Publication and recovery

**Bronze.** Every stream and part receives the same UTC start-time sync ID. The writer uploads all parts under `airbyte/_staging/<batch>/`, creates a journal under `airbyte/_pending/`, and then conditionally copies into the Airbyte stream prefixes. If a copy fails, the writer rolls back the parts it owns. A crash or an S3 failure during rollback can leave a journal and some final keys. The next ingest stops when it detects the journal. Dagster queues a single run at a time. When running standalone dbt against production S3, check that no bronze promotion is underway or pending. Existing dbt globs can see final keys individually during promotion. [S3 consistency model](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html#ConsistencyModel)

To recover an interrupted promotion, pause Dagster and list the journals. Inspect the selected journal and each listed final key. Complete the copies from the recorded staging prefix, with the final key precondition `--if-none-match '*'`. For already present keys, check that `bronze-batch` metadata matches the journal filename stem. Remove the journal only once all its final objects exist and match the batch. A bucket lifecycle rule scoped to `airbyte/_staging/` may expire abandoned staging objects after the recovery window.

```bash
BUCKET=divergence-index-data-lqpeej
aws s3 ls "s3://$BUCKET/airbyte/_pending/"
read -r -p 'Journal filename: ' JOURNAL
aws s3 cp "s3://$BUCKET/airbyte/_pending/$JOURNAL" -
# Once every listed final key is verified
aws s3 rm "s3://$BUCKET/airbyte/_pending/$JOURNAL"
```

**MotherDuck.** The publisher attaches the local warehouse read-only while building `__next` tables and checking counts and column order. It detaches the local catalog, then swaps all eight tables and appends `meta.publish_log` in one transaction. The panel count and column order must match the Parquet before commit and are checked again after commit. Remote transaction behavior requires a live smoke test. [MotherDuck local-to-cloud workflow](https://motherduck.com/blog/take-flight-with-dbt-and-duckdb-dropping-dev-warehouse-costs-to-zero/), [Transaction control](https://motherduck.com/glossary/transactions/)

**S3 gold.** The four files are uploaded to immutable `gold/runs/<run_id>/` keys before the database swap. After MotherDuck commits, the publisher copies them to `gold/latest/` and atomically advances `gold/latest/manifest.json`. Readers should resolve file keys from that manifest to get a consistent set. S3 and MotherDuck commit independently. If the database commits and the S3 refresh fails, the old manifest remains authoritative and the four direct aliases may be mixed. To resume, use the original export directory before starting a newer run. The export metadata provides the publish run ID. The publisher recognizes the committed run log and retries the S3 refresh without writing another log row. [S3 consistency model](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html#ConsistencyModel)

Resume an interrupted gold publication on EC2 after active Dagster runs finish.

```bash
read -r -p 'Original Dagster run ID: ' RUN_ID
sudo systemd-run --wait --collect --pipe --uid=divergence \
  --working-directory=/opt/divergence-index \
  --property=EnvironmentFile=/etc/divergence/env \
  --setenv=DIVERGENCE_AWS_CHAIN=instance \
  --setenv=DUCKDB_PATH=/var/lib/divergence/warehouse.duckdb \
  --setenv="DIVERGENCE_GOLD_DIR=/var/lib/divergence/dagster/storage/$RUN_ID/gold" \
  /opt/divergence-index/.venv/bin/python -m pipeline.publish.publish_motherduck
```

For rollback, pause the schedule and wait for active runs to finish. In MotherDuck, identify the last good run and record the log before any rollback.

```sql
SELECT run_id, git_commit, published_at, row_counts, latest_complete_common_quarter
FROM divergence_index.meta.publish_log ORDER BY published_at DESC;
SELECT * FROM md_information_schema.database_snapshots;
```

Download and check the corresponding archived panel and JSON files. Clone an available snapshot into a recovery database and confirm its publish log and panel match the chosen run before restoring production. Snapshot availability depends on retention.

```sql
CREATE DATABASE divergence_index_recovery
FROM divergence_index (SNAPSHOT_ID '<SNAPSHOT_ID>');
-- Preserve the current state and audit log under a unique name before restoring
CREATE SNAPSHOT OF divergence_index NAME 'before_gold_rollback';
-- After checking the exact run in the recovery database
ALTER DATABASE divergence_index SET SNAPSHOT TO (SNAPSHOT_ID '<SNAPSHOT_ID>');
```

Restore S3 aliases and repoint its manifest to that run. Use the `published_at` from the good run's log in ISO format. S3 run archives stay intact. [MotherDuck point-in-time restore](https://motherduck.com/blog/point-in-time-restore/)

```bash
BUCKET=divergence-index-data-lqpeej
read -r -p 'Last good run ID: ' RUN_ID
read -r -p 'Last good published_at (ISO format): ' PUBLISHED_AT
ROLLBACK_DIR=$(mktemp -d)
aws s3 cp --recursive "s3://$BUCKET/gold/runs/$RUN_ID/" "$ROLLBACK_DIR/"
for filename in divergence_panel.parquet divergence_panel.csv pipeline_metadata.json component_contributions.json; do
  test -s "$ROLLBACK_DIR/$filename" || break
  aws s3 cp "s3://$BUCKET/gold/runs/$RUN_ID/$filename" "s3://$BUCKET/gold/latest/$filename" || break
done
```

Update the manifest after all four copies succeed.

```bash
python3 - "$RUN_ID" "$PUBLISHED_AT" "$ROLLBACK_DIR" <<'PY' | aws s3 cp - "s3://$BUCKET/gold/latest/manifest.json" --content-type application/json
from pathlib import Path
import hashlib, json, sys
run_id, published_at, directory = sys.argv[1:]
names = ("divergence_panel.parquet", "divergence_panel.csv",
         "pipeline_metadata.json", "component_contributions.json")
files = {name: {"key": f"gold/runs/{run_id}/{name}",
                "sha256": hashlib.sha256((Path(directory) / name).read_bytes()).hexdigest()}
         for name in names}
print(json.dumps({"run_id": run_id, "published_at": published_at, "files": files}))
PY
```

For Juhi, open **Settings → Access tokens → Create token → Read Scaling Token** in MotherDuck. Share it via a secret manager. It can read every database accessible to the issuing account. [MotherDuck read scaling tokens](https://motherduck.com/blog/read-scaling-preview/)

## 6. Offline checks

From the repo root, replay the checked-in vintage through the same S3 writer. Omit `--fixture-vintage` to fetch fresh observations from OECD and BIS into the local mirror. Keep local exports in an ignored directory to preserve the tracked files.

```bash
uv sync --frozen
uv run pytest
export DUCKDB_PATH="$PWD/data/_s3_mirror/warehouse.duckdb"
export DIVERGENCE_GOLD_DIR="$PWD/data/_s3_mirror/gold"
uv run python pipeline/ingest/run_ingest.py --dest s3 --s3-root data/_s3_mirror/airbyte \
  --fixture-vintage 2026-11-22
uv run dbt build --project-dir pipeline/transform --profiles-dir pipeline/transform \
  --target offline --vars '{bronze_source: s3, s3_bronze_root: data/_s3_mirror/airbyte}'
uv run python pipeline/publish/export_gold.py
uv run python pipeline/publish/publish_motherduck.py --dry-run

export DAGSTER_HOME="$PWD/.dagster"
mkdir -p "$DAGSTER_HOME"
cp pipeline/orchestration/dagster.yaml "$DAGSTER_HOME/dagster.yaml"
export DIVERGENCE_BRONZE_ROOT="$PWD/data/_s3_mirror/dagster"
export DIVERGENCE_FIXTURE_VINTAGE=2026-11-22
export DIVERGENCE_PUBLISH_DRY_RUN=1
uv run dagster definitions validate -m pipeline.orchestration.definitions
uv run dagster dev -w pipeline/orchestration/workspace.yaml -h 127.0.0.1 -p 3000
```

Launch `monthly_refresh` in the UI on port 3000 to exercise the complete dry-run path.

| Environment variable | Value |
| --- | --- |
| `DUCKDB_PATH` | Warehouse path. Defaults to `data/warehouse.duckdb`. EC2 uses `/var/lib/divergence/warehouse.duckdb`. |
| `DIVERGENCE_AWS_PROFILE` | Named laptop AWS profile, defaults to `divergence-reader`. |
| `DIVERGENCE_AWS_CHAIN` | DuckDB credential chain, defaults to `config`. EC2 uses `instance`. Python uses the named profile for `config` and the SDK default chain otherwise. |
| `MOTHERDUCK_TOKEN` | Write token, fetched from SSM on EC2. |
| `MOTHERDUCK_DATABASE` | Defaults to `divergence_index`. |
| `ALERT_WEBHOOK_URL` | Optional Slack-compatible endpoint, fetched from SSM on EC2. |
| `DAGSTER_HOME` | Dagster SQLite state and artifact directory. EC2 uses `/var/lib/divergence/dagster`. |
| `DIVERGENCE_BRONZE_ROOT` | Dagster bronze destination and dbt source root. Defaults to the production S3 prefix. |
| `DIVERGENCE_FIXTURE_VINTAGE` | Optional tracked vintage for an offline mirror replay. |
| `DIVERGENCE_PUBLISH_DRY_RUN` | Set to `1` to print the publication plan without connecting to AWS or MotherDuck. |
| `DIVERGENCE_GOLD_DIR` | Export and publish directory. Defaults to `data/gold/`. Dagster supplies a run-specific directory. |
| `DBT_RUN_RESULTS` | Export validation artifact. Defaults to `pipeline/transform/target/run_results.json`. Dagster supplies the current build's path. |
| `DO_NOT_TRACK` | Set to `1` to disable PyAirbyte telemetry. |
| `AWS_REGION` | The services use `ap-south-1`. |
| `UV_PYTHON_INSTALL_DIR` | Bootstrap and deploy set it to `/opt/divergence-index/.python` for a service-readable interpreter. |
