#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID != 0 ]]; then
    printf '%s\n' 'Run deploy.sh as root after active runs finish.' >&2
    exit 1
fi

repo=/opt/divergence-index
state=/var/lib/divergence
mode=${1:-}
if [[ -z $mode ]]; then
    git -C "$repo" pull --ff-only
    # The pull may have rewritten this very script, and bash reads scripts as it runs.
    # Start the updated copy so the rest of the steps are the new ones.
    exec bash "$repo/infra/ec2/deploy.sh" --after-pull
fi
if [[ $mode != --install-units ]]; then
    UV_PYTHON_INSTALL_DIR="$repo/.python" /usr/local/bin/uv sync --directory "$repo" --frozen --no-dev
fi

# Grant write access to scratch data while keeping code and Git metadata root-owned.
chown -hR divergence:divergence "$repo/data"
runuser -u divergence -- git config --file "$state/.gitconfig" --replace-all safe.directory "$repo" "^$repo$"
install -d -o divergence -g divergence -m 0750 "$state/dbt/logs" "$state/dbt/target" "$state/airbyte/logs" "$state/airbyte/cache" "$state/airbyte/tmp"
runuser -u divergence -- install -m 0600 "$repo/pipeline/orchestration/dagster.yaml" "$state/dagster/dagster.yaml"
install -m 0644 "$repo"/infra/ec2/dagster-*.service /etc/systemd/system/
systemctl daemon-reload
if [[ $mode != --install-units ]]; then
    systemctl restart dagster-daemon.service dagster-webserver.service
fi
