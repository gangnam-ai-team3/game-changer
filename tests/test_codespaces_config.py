from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_codespaces_public_demo_configuration() -> None:
    config = json.loads(
        (ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")
    )
    script = ROOT / "scripts" / "start_codespace_demo.sh"
    dockerfile = (ROOT / ".devcontainer" / "Dockerfile").read_text(encoding="utf-8")

    assert config["build"]["dockerfile"] == "Dockerfile"
    assert "python:1-3.12-bookworm" in dockerfile
    assert "/etc/apt/sources.list.d/yarn.list" in dockerfile
    assert config["features"]["ghcr.io/devcontainers/features/node:1"]["version"] == "24"
    assert "ghcr.io/devcontainers/features/sshd:1" in config["features"]
    assert "uv==0.11.26" in config["postCreateCommand"]
    assert config["forwardPorts"] == [3000]
    assert config["portsAttributes"]["8000"]["onAutoForward"] == "ignore"
    assert config["otherPortsAttributes"]["onAutoForward"] == "ignore"
    assert "ANTHROPIC_API_KEY" in config["secrets"]
    assert os.access(script, os.X_OK)
    subprocess.run(["bash", "-n", script], check=True)
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            (
                "import config from './frontend/next.config.mjs';"
                "const rules = await config.rewrites();"
                "if (rules.length !== 1 || rules[0].source !== '/api/:path*' || "
                "rules[0].destination !== 'http://127.0.0.1:8000/api/:path*') "
                "process.exit(1);"
            ),
        ],
        cwd=ROOT,
        check=True,
    )

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    missing_key = subprocess.run(
        [script], env=env, text=True, capture_output=True, check=False
    )
    assert missing_key.returncode == 1
    assert "ANTHROPIC_API_KEY" in missing_key.stderr
