"""仅清理本次评测随机账号拥有的项目；失败保留清理账本供诊断。"""

from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.db import transaction

from core.cleanup import create_cleanup, execute
from core.cleanup_plan import Plan
from core.graph import purge_projection
from core.models import CleanupRequest, GraphTombstone, Project


def remove_project(project, user):
    prefixes = [
        "reading-eval-",
        "review-eval-",
        "expression-eval-",
        "feedback-eval-",
        "impact-eval-",
    ]
    if (
        not settings.DEBUG
        or project.owner_id != user.pk
        or project.name != user.username
        or not any(user.username.startswith(prefix) for prefix in prefixes)
    ):
        raise ValueError("仅可清理评测创建的专用项目。")
    project_id = project.pk
    with patch("core.cleanup.dispatch"), transaction.atomic():
        locked = Project.objects.select_for_update().get(pk=project_id)
        record = create_cleanup(Plan(locked), user, str(uuid4()), "0" * 64)
    execute(record.pk)
    record.refresh_from_db()
    if record.status != "succeeded":
        raise RuntimeError(f"自制评测清理未完成，保留清理记录 {record.pk}。")
    with transaction.atomic():
        # 与图墓碑消费者串行，避免它在演练清理后重新留下测试标记。
        list(GraphTombstone.objects.select_for_update().filter(project_id=project_id))
        purge_projection(project_id)
        GraphTombstone.objects.filter(project_id=project_id).delete()
        CleanupRequest.objects.filter(pk=record.pk).delete()
        user.delete()
