from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from core import health
from worker.tasks import ping

CHECKS = ["postgres", "neo4j", "s3", "redis", "worker"]


@pytest.fixture
def dependencies(monkeypatch):
    mocks = {}
    for name in CHECKS:
        mocks[name] = MagicMock()
        monkeypatch.setattr(health, f"check_{name}", mocks[name])
    return mocks


def test_liveness_does_not_require_database():
    response = APIClient().get("/api/v1/health/live/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api", "version": "0.1.0"}


def test_ready(dependencies):
    response = APIClient().get("/api/v1/health/ready/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert all(value == "ok" for value in response.json()["checks"].values())
    for mock in dependencies.values():
        mock.assert_called_once()


@pytest.mark.parametrize("failed", CHECKS)
def test_failure_is_503_without_secret_leak(dependencies, failed, caplog):
    dependencies[failed].side_effect = RuntimeError("password=private-test-secret")
    response = APIClient().get("/api/v1/health/ready/")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert "unavailable" in response.json()["checks"].values()
    assert b"private-test-secret" not in response.content
    assert "private-test-secret" not in caplog.text
    if failed == "redis":
        dependencies["worker"].assert_not_called()


def test_worker_absent_is_not_ready():
    with patch("worker.app.app.control.inspect") as inspect:
        inspect.return_value.ping.return_value = None
        with pytest.raises(RuntimeError, match="Worker"):
            health.check_worker()


def test_ping_payload_without_broker():
    assert ping.run() == {"status": "ok", "service": "worker"}


def test_s3_client_is_closed_without_context_manager_protocol():
    client = MagicMock(spec=["list_buckets", "close"])
    with patch("core.health.s3_client", return_value=client):
        health.check_s3()
    client.list_buckets.assert_called_once()
    client.close.assert_called_once()


def test_pgvector_missing_is_not_ready():
    with patch("core.health.connection") as connection:
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = None
        with pytest.raises(RuntimeError, match="pgvector"):
            health.check_postgres()


def test_pending_migration_is_not_ready():
    with (
        patch("core.health.connection") as connection,
        patch("core.health.MigrationExecutor") as cls,
    ):
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = ("0.8.7",)
        cls.return_value.migration_plan.return_value = [object()]
        with pytest.raises(RuntimeError, match="未应用迁移"):
            health.check_postgres()
