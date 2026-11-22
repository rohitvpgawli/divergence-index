#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID != 0 ]]; then
    printf '%s\n' 'Run bootstrap.sh as root.' >&2
    exit 1
fi

repo=/opt/divergence-index
state=/var/lib/divergence
ref=${1:-main}
if [[ ! -x /usr/local/bin/aws ]]; then
    printf '%s\n' 'Expected the existing AWS CLI v2 at /usr/local/bin/aws.' >&2
    exit 1
fi
apt-get update
apt-get install -y ca-certificates curl git
if ! id divergence >/dev/null 2>&1; then
    useradd --system --home-dir "$state" --shell /usr/sbin/nologin divergence
fi
install -d -o divergence -g divergence -m 0750 "$state" "$state/dagster"
install -d -m 0755 "$repo"
install -d -o divergence -g divergence -m 0750 /etc/divergence

if [[ ! -x /usr/local/bin/uv ]]; then
    curl -fsSL https://astral.sh/uv/install.sh |
        env UV_UNMANAGED_INSTALL=/usr/local/bin sh
fi

if [[ ! -d $repo/.git ]]; then
    git clone --branch "$ref" https://github.com/rohitvpgawli/divergence-index.git "$repo"
fi
git -C "$repo" remote set-url --push origin DISABLED
UV_PYTHON_INSTALL_DIR="$repo/.python" /usr/local/bin/uv sync --directory "$repo" --python 3.12 --frozen --no-dev
bash "$repo/infra/ec2/deploy.sh" --install-units
systemctl enable --now dagster-daemon.service dagster-webserver.service
