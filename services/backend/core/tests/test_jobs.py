"""仅使用自制文本与独立 PostgreSQL 测试库。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient

from core.jobs.service import claim, dispatch, fail, heartbeat, publish, recover_jobs
from core.models import Job, Project, ProjectMember, ProjectPolicy
from worker.tasks import execute_job

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def context():
    user = get_user_model().objects.create_user(username="job-author")
    client = APIClient()
    client.force_authenticate(user)
    project = Project.objects.create(owner=user, name="自制任务测试")
    ProjectPolicy.objects.create(project=project, version=1, created_by=user)
    return client, project, user


def url(project, suffix=""):
    return f"/api/v1/projects/{project.pk}/jobs/{suffix}"


def payload(**changes):
    return {
        "kind": "sample",
        "idempotency_key": "request-1",
        "policy_version": 1,
        "input_snapshot": {"text": "自制测试", "source_version": 1, "steps": 1},
        **changes,
    }


def create(context, **changes):
    client, project, _ = context
    response = client.post(url(project), payload(**changes), format="json")
    assert response.status_code == 201, response.data
    return Job.objects.get(pk=response.data["id"])


def test_create_idempotency_and_different_input_conflict(context):
    client, project, _ = context
    job = create(context)
    assert client.post(url(project), payload(), format="json").data["id"] == str(job.pk)
    assert Job.objects.count() == 1
    assert client.post(url(project), payload(ai_action="reading"), format="json").status_code == 409
    assert client.post(url(project), payload(kind="unknown"), format="json").status_code == 400
    assert client.post(url(project), payload(policy_version=2), format="json").status_code == 409


def test_sample_execution_and_duplicate_delivery(context):
    job = create(context)
    execute_job(str(job.pk))
    execute_job(str(job.pk))
    job.refresh_from_db()
    assert job.status == "succeeded"
    assert job.output == {"characters": 4, "source_version": 1}
    assert job.progress == 100
    assert job.attempts.count() == 1
    assert job.attempts.get().finished_at is not None


def test_cancel_is_idempotent_and_late_result_rejected(context):
    client, project, _ = context
    job = claim(create(context).pk)
    cancel = url(project, f"{job.pk}/cancel/")
    for _ in range(2):
        assert client.post(cancel, {"generation": 1}).data["status"] == "cancelled"
    assert not heartbeat(job.pk, 1, 40)
    assert not publish(job.pk, 1, {"late": True})
    job.refresh_from_db()
    assert job.output is None
    assert job.attempts.get().status == "cancelled"


def test_expiry_retry_new_generation_and_stale_worker(context):
    client, project, _ = context
    job = claim(create(context).pk)
    Job.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    recover_jobs()
    job.refresh_from_db()
    assert job.status == "failed" and job.retryable
    retry = url(project, f"{job.pk}/retry/")
    for _ in range(2):
        assert client.post(retry, {"generation": 1}).data["status"] == "queued"
    second = claim(job.pk)
    assert second.generation == 2
    assert not heartbeat(job.pk, 1, 50)
    assert not publish(job.pk, 1, {"late": True})
    assert client.post(retry, {"generation": 1}).status_code == 409
    assert publish(job.pk, 2, {"valid": True})
    assert list(job.attempts.order_by("generation").values_list("status", flat=True)) == [
        "failed",
        "succeeded",
    ]


@pytest.mark.parametrize("change", ["policy", "member", "inactive"])
def test_authorization_checked_before_call_and_publication(context, change):
    client, project, owner = context
    author = get_user_model().objects.create_user(username="coauthor")
    member = ProjectMember.objects.create(project=project, user=author, role="author")
    client.force_authenticate(author)
    ProjectPolicy.objects.filter(project=project).update(
        verified=True, source="自制规则", source_version="1", allowed_actions=["reading"]
    )
    job = claim(create(context, ai_action="reading").pk)
    assert heartbeat(job.pk, 1, 10)
    if change == "policy":
        ProjectPolicy.objects.create(project=project, version=2, created_by=owner)
    elif change == "member":
        member.delete()
    else:
        author.is_active = False
        author.save()
    assert not publish(job.pk, 1, {"invalid": True})
    assert not heartbeat(job.pk, 1, 20)
    job.refresh_from_db()
    assert job.status == "cancelled" and job.output is None
    assert job.error_code == "authorization_changed"


def test_cross_project_and_reviewer_control_denied(context):
    client, project, user = context
    job = create(context)
    other = Project.objects.create(owner=user, name="另一个自制项目")
    assert client.get(url(other, f"{job.pk}/")).status_code == 404
    outsider = get_user_model().objects.create_user(username="outsider")
    client.force_authenticate(outsider)
    assert client.get(url(project, f"{job.pk}/")).status_code == 404
    ProjectMember.objects.create(project=project, user=outsider, role="reviewer")
    assert client.get(url(project, f"{job.pk}/")).status_code == 200
    assert client.post(url(project), payload(), format="json").status_code == 403
    assert client.post(url(project, f"{job.pk}/cancel/"), {"generation": 0}).status_code == 403


def test_dispatch_failure_is_durable_and_recovery_requeues(context):
    job = create(context)
    with patch("worker.tasks.execute_job.apply_async", side_effect=ConnectionError("secret")):
        dispatch(job.pk)
    job.refresh_from_db()
    assert job.status == "queued" and job.error_code == "dispatch_failed"
    assert "secret" not in job.error_message


def test_nonretryable_failure_and_attempt_limit(context):
    client, project, _ = context
    job = claim(create(context).pk)
    fail(job.pk, 1, retryable=False)
    retry = url(project, f"{job.pk}/retry/")
    assert client.post(retry, {"generation": 1}).status_code == 400
    Job.objects.filter(pk=job.pk).update(retryable=True, generation=3)
    assert client.post(retry, {"generation": 3}).status_code == 400


@pytest.mark.django_db(transaction=True)
def test_concurrent_create_claim_and_committed_dispatch(context):
    _, project, user = context
    barrier = Barrier(2)

    def submit(_):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=user.pk))
            barrier.wait(timeout=10)
            return client.post(url(project), payload(), format="json").status_code
        finally:
            close_old_connections()

    with (
        patch("core.jobs.views.dispatch") as send,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        assert sorted(pool.map(submit, range(2))) == [200, 201]
        assert send.call_count == 1
    job = Job.objects.get()
    with patch("core.jobs.service.dispatch") as send:
        recover_jobs()
        send.assert_called_once_with(job.pk)

    barrier = Barrier(2)

    def acquire(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return claim(job.pk) is not None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(acquire, range(2))) == [False, True]
    assert job.attempts.count() == 1
    assert APIClient().get(url(project, f"{uuid4()}/")).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_real_worker_restart_and_retry(context, tmp_path):
    """独立测试库与专用队列，真实杀掉 Worker 后恢复；不影响开发 Worker。"""
    import os
    import subprocess
    import sys
    import time

    from django.conf import settings
    from django.db import connection

    from worker.app import app

    client, project, user = context
    queue = f"job-test-{uuid4().hex}"
    environment = {**os.environ, "POSTGRES_DB": connection.settings_dict["NAME"]}
    log = (tmp_path / "worker.log").open("w")
    process = None

    def start_worker():
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "worker.app",
                "worker",
                "--pool=solo",
                "--queues",
                queue,
                "--hostname",
                queue,
                "--without-gossip",
                "--without-mingle",
                "--loglevel=warning",
            ],
            cwd=settings.BASE_DIR,
            env=environment,
            stdout=log,
            stderr=log,
        )

    def wait_until(predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        raise AssertionError("测试 Worker 未在期限内完成状态转换。")

    def state(expected):
        return Job.objects.get(pk=job.pk).status == expected

    try:
        process = start_worker()
        # ping 同一专用队列，确认真实进程可以消费后再开始故障演练。
        app.send_task("system.ping", queue=queue).get(timeout=20)
        job = Job.objects.create(
            project=project,
            created_by=user,
            kind="sample",
            idempotency_key=queue,
            policy_version=1,
            input_snapshot={"text": "自制测试", "source_version": 1, "steps": 10},
        )
        execute_job.apply_async(args=[str(job.pk)], queue=queue)
        wait_until(lambda: state("running"))
        process.kill()
        process.wait(timeout=10)
        # 缩短时钟等待；状态恢复仍经过真实 PostgreSQL 与完整租约判断。
        Job.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        recover_jobs()
        assert state("failed")
        process = start_worker()
        app.send_task("system.ping", queue=queue).get(timeout=20)
        with patch(
            "core.jobs.views.dispatch",
            lambda jid: execute_job.apply_async(args=[str(jid)], queue=queue),
        ):
            response = client.post(url(project, f"{job.pk}/retry/"), {"generation": 1})
            assert response.status_code == 200
        wait_until(lambda: state("succeeded"))
        job.refresh_from_db()
        assert job.generation == 2 and job.output["characters"] == 4
        assert list(job.attempts.order_by("generation").values_list("status", flat=True)) == [
            "failed",
            "succeeded",
        ]
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        with app.connection() as broker:
            broker.default_channel.queue_delete(queue)
        log.close()


def test_disabled_ai_rejected_and_queued_revocation_stops_claim(context):
    client, project, owner = context
    assert client.post(url(project), payload(ai_action="reading"), format="json").status_code == 403
    assert not Job.objects.exists()
    job = create(context)
    ProjectPolicy.objects.create(project=project, version=2, created_by=owner)
    assert claim(job.pk) is None
    job.refresh_from_db()
    assert job.status == "cancelled" and job.attempts.count() == 0


def test_heartbeat_renews_lease_and_nonretryable_worker_error(context):
    job = claim(create(context).pk)
    lease = job.lease_until
    assert heartbeat(job.pk, 1, 25)
    job.refresh_from_db()
    assert job.lease_until > lease and job.progress == 25
    # 不受支持的内部类型不能误标成功，且不会形成自动重试风暴。
    fail(job.pk, 1, retryable=True)
    Job.objects.filter(pk=job.pk).update(status="queued", kind="unsupported")
    execute_job(str(job.pk))
    job.refresh_from_db()
    assert job.status == "failed" and not job.retryable
    assert job.error_code == "unknown_kind" and job.attempts.count() == 2
