import logging
from contextlib import closing

import boto3
from botocore.config import Config
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from neo4j import GraphDatabase
from redis import Redis

logger = logging.getLogger(__name__)


def check_postgres():
    with connection.cursor() as cursor:
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        if cursor.fetchone() is None:
            raise RuntimeError("pgvector 尚未迁移")
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise RuntimeError("数据库存在未应用迁移")


def check_neo4j():
    with GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        connection_timeout=3,
        connection_acquisition_timeout=3,
        max_transaction_retry_time=0,
    ) as driver:
        driver.verify_connectivity()


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(
            connect_timeout=3,
            read_timeout=3,
            retries={"max_attempts": 0},
            s3={"addressing_style": "path"},
        ),
    )


def check_s3():
    with closing(s3_client()) as client:
        client.list_buckets()


def check_redis():
    with Redis.from_url(settings.REDIS_URL, socket_connect_timeout=3, socket_timeout=3) as client:
        client.ping()


def check_worker():
    from worker.app import app

    if not app.control.inspect(timeout=2).ping():
        raise RuntimeError("Worker 尚未响应")


def readiness():
    checks = {}
    for name, check in [
        ("postgresql", check_postgres),
        ("neo4j", check_neo4j),
        ("seaweedfs", check_s3),
        ("redis", check_redis),
        ("worker", check_worker),
    ]:
        if name == "worker" and checks["redis"] != "ok":
            checks[name] = "unavailable"
            continue
        try:
            check()
            checks[name] = "ok"
        except Exception as error:
            # 不返回或记录包含连接地址、凭据的底层异常正文。
            logger.warning("dependency=%s error_type=%s", name, type(error).__name__)
            checks[name] = "unavailable"
    return {
        "status": "ok" if all(v == "ok" for v in checks.values()) else "degraded",
        "checks": checks,
    }
