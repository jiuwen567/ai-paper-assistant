import uuid
from contextlib import closing

import pytest
from botocore.exceptions import ClientError
from django.core.management import call_command
from django.db import connection
from django.test import override_settings

from core.health import readiness, s3_client

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_empty_database_has_vector_and_supports_vector_query():
    # pytest-django 从空测试库执行真实迁移；不使用 SQLite 替代。
    with connection.cursor() as cursor:
        cursor.execute("SELECT '[1,2,3]'::vector <-> '[1,2,3]'::vector")
        assert cursor.fetchone()[0] == 0
    call_command("migrate", check_unapplied=True, verbosity=0)


def test_real_service_connections():
    assert readiness()["status"] == "ok"


def test_real_worker_round_trip():
    call_command("check_worker")


def test_s3_rejects_invalid_credentials():
    with override_settings(S3_SECRET_KEY="invalid-test-secret"), closing(s3_client()) as client:
        with pytest.raises(ClientError) as error:
            client.list_buckets()
        assert error.value.response["ResponseMetadata"]["HTTPStatusCode"] == 403


def test_s3_round_trip():
    bucket = f"paper-test-{uuid.uuid4().hex}"
    with closing(s3_client()) as client:
        client.create_bucket(Bucket=bucket)
        try:
            client.put_object(Bucket=bucket, Key="self-authored.txt", Body=b"local test fixture")
            body = client.get_object(Bucket=bucket, Key="self-authored.txt")["Body"]
            try:
                assert body.read() == b"local test fixture"
            finally:
                body.close()
        finally:
            client.delete_object(Bucket=bucket, Key="self-authored.txt")
            client.delete_bucket(Bucket=bucket)
