"""独立演示配置不覆盖现有凭据，宿主端口与客户端地址保持一致。"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def initialize(directory, offset):
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/init_dev.py"),
            "--directory",
            str(directory),
            "--port-offset",
            str(offset),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_isolated_configuration_preserves_credentials_and_ports(tmp_path):
    directory = tmp_path / "demo"
    assert initialize(directory, 20000).returncode == 0
    path = directory / ".env"
    before = path.read_bytes()
    env = dict(
        line.split("=", 1)
        for line in before.decode().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert env["WEB_PORT"] == "25173" and env["POSTGRES_PORT"] == "25432"
    assert env["REDIS_URL"] == f"redis://127.0.0.1:{env['REDIS_PORT']}/0"
    assert env["NEO4J_URI"] == f"bolt://127.0.0.1:{env['NEO4J_BOLT_PORT']}"
    assert env["S3_ENDPOINT_URL"] == f"http://127.0.0.1:{env['S3_PORT']}"
    assert f"http://localhost:{env['WEB_PORT']}" in env["DJANGO_CSRF_TRUSTED_ORIGINS"]
    credentials = json.loads((directory / ".local/seaweedfs/s3.json").read_text())
    assert credentials["identities"][0]["credentials"][0] == {
        "accessKey": env["S3_ACCESS_KEY"],
        "secretKey": env["S3_SECRET_KEY"],
    }
    assert path.stat().st_mode & 0o077 == 0
    assert initialize(directory, 0).returncode == 0
    assert path.read_bytes() == before


def test_invalid_ports_are_rejected_before_creating_configuration(tmp_path):
    directory = tmp_path / "invalid"
    assert initialize(directory, 60000).returncode != 0
    assert not directory.exists()
