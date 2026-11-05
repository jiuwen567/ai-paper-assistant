"""生成仅用于本地开发的配置；重复执行保留已有凭据。"""

import argparse
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT, help="独立环境的配置目录")
    parser.add_argument("--port-offset", type=int, default=0, help="新配置所有宿主端口的偏移量")
    args = parser.parse_args()
    if not 0 <= args.port_offset <= 57202:
        parser.error("端口偏移量须在 0–57202 之间。")
    os.umask(0o077)
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    env_path = directory / ".env"
    if not env_path.exists():
        text = (ROOT / ".env.example").read_text()
        changes = {
            key: secrets.token_hex(24)
            for key in [
                "DJANGO_SECRET_KEY",
                "POSTGRES_PASSWORD",
                "NEO4J_PASSWORD",
                "S3_ACCESS_KEY",
                "S3_SECRET_KEY",
            ]
        }
        ports = {
            key: value + args.port_offset
            for key, value in {
                "POSTGRES_PORT": 5432,
                "REDIS_PORT": 6379,
                "NEO4J_HTTP_PORT": 7474,
                "NEO4J_BOLT_PORT": 7687,
                "S3_PORT": 8333,
                "API_PORT": 8000,
                "WEB_PORT": 5173,
            }.items()
        }
        changes.update(ports)
        changes.update(
            {
                "NEO4J_URI": f"bolt://127.0.0.1:{ports['NEO4J_BOLT_PORT']}",
                "S3_ENDPOINT_URL": f"http://127.0.0.1:{ports['S3_PORT']}",
                "REDIS_URL": f"redis://127.0.0.1:{ports['REDIS_PORT']}/0",
                "DJANGO_CSRF_TRUSTED_ORIGINS": f"http://localhost:{ports['WEB_PORT']},http://127.0.0.1:{ports['WEB_PORT']}",
            }
        )
        text = (
            "\n".join(
                f"{line.split('=', 1)[0]}={changes[line.split('=', 1)[0]]}"
                if "=" in line and line.split("=", 1)[0] in changes
                else line
                for line in text.splitlines()
            )
            + "\n"
        )
        env_path.write_text(text)
        print("已生成独立 .env（随机本地凭据）")
    values = dict(
        line.split("=", 1)
        for line in env_path.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    required = [
        "DJANGO_SECRET_KEY",
        "POSTGRES_PASSWORD",
        "NEO4J_PASSWORD",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
    ]
    if any(not values.get(k) or values[k].startswith("replace-") for k in required):
        raise SystemExit(".env 包含占位值或缺失字段。请填写本地值，或移走示例副本后重跑。")
    # 仅存放公开模型文件；提前建目录，避免 Compose 以 root 创建后阻止宿主机准备模型。
    model_dir = directory / ".local" / "embeddings"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_dir.chmod(0o755)
    config_dir = directory / ".local" / "seaweedfs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.chmod(0o700)
    config = {
        "identities": [
            {
                "name": "local-development",
                "credentials": [
                    {"accessKey": values["S3_ACCESS_KEY"], "secretKey": values["S3_SECRET_KEY"]}
                ],
                "actions": ["Admin", "Read", "Write", "List", "Tagging"],
            }
        ]
    }
    config_path = config_dir / "s3.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    # 仅文件被只读挂载。容器 UID 可能不同，宿主机的访问由上层私有目录限制。
    config_path.chmod(0o644)
    print("已同步 .local/seaweedfs/s3.json；已有 .env 不会被覆盖")


if __name__ == "__main__":
    main()
