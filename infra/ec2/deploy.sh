#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID != 0 ]]; then
    printf '%s\n' 'Run deploy.sh as root after active runs finish.' >&2
    exit 1
fi

repo=/opt/divergence-index
state=/var/lib/divergence
if [[ ${1:-} != --install-units ]]; then
    git -C "$repo" pull --ff-only
    UV_PYTHON_INSTALL_DIR="$repo/.python" /usr/local/bin/uv sync --directory "$repo" --frozen --no-dev
    runuser -u divergence -- install -m 0600 "$repo/pipeline/orchestration/dagster.yaml" "$state/dagster/dagster.yaml"
fi
install -m 0644 "$repo"/infra/ec2/dagster-*.service /etc/systemd/system/
systemctl daemon-reload
if [[ ${1:-} != --install-units ]]; then
    systemctl restart dagster-daemon.service dagster-webserver.service
fi
