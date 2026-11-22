#!/usr/bin/env bash
set -euo pipefail
umask 077
exec /usr/bin/python3 - <<'PY'
import json
import os
import subprocess
import tempfile
from pathlib import Path


def parameter(name, optional=False):
    result = subprocess.run(
        ["aws", "ssm", "get-parameter", "--region", "ap-south-1", "--with-decryption",
         "--name", f"/divergence/{name}", "--output", "json", "--no-cli-pager"],
        capture_output=True, text=True,
    )
    if result.returncode:
        if optional and "(ParameterNotFound)" in result.stderr:
            return None
        raise SystemExit(f"Unable to fetch /divergence/{name} from SSM")
    value = json.loads(result.stdout)["Parameter"]["Value"]
    if not value or any(char in value for char in ("\r", "\n", "\0")):
        raise SystemExit(f"Invalid value in /divergence/{name}")
    return value


def escape(value):
    # systemd EnvironmentFile double-quoted value escaping
    return value.replace("\\", "\\\\").replace('"', '\\"')


values = {
    "MOTHERDUCK_TOKEN": parameter("motherduck_token"),
    "ALERT_WEBHOOK_URL": parameter("alert_webhook_url", optional=True),
}
with tempfile.NamedTemporaryFile(mode="w", dir="/etc/divergence", delete=False) as out:
    temp = Path(out.name)
    try:
        for name, value in values.items():
            if value is not None:
                out.write(f'{name}="{escape(value)}"\n')
        out.flush()
        os.replace(temp, "/etc/divergence/env")
    finally:
        temp.unlink(missing_ok=True)
PY
