"""生成仅用于本地开发的配置；重复执行保留已有凭据。"""

import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.umask(0o077)
    env_path = ROOT / ".env"
    if not env_path.exists():
        text = (ROOT / ".env.example").read_text()
        for key in [
            "DJANGO_SECRET_KEY",
            "POSTGRES_PASSWORD",
            "NEO4J_PASSWORD",
            "S3_ACCESS_KEY",
            "S3_SECRET_KEY",
        ]:
            lines = text.splitlines()
            text = (
                "\n".join(
                    f"{key}={secrets.token_hex(24)}" if line.startswith(f"{key}=") else line
                    for line in lines
                )
                + "\n"
            )
        env_path.write_text(text)
        print("已生成 .env（随机本地凭据）")
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
    model_dir = ROOT / ".local" / "embeddings"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_dir.chmod(0o755)
    config_dir = ROOT / ".local" / "seaweedfs"
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
