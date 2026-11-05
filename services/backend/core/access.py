"""API 与 Worker 共用的权限入口；每次调用读取当前身份、成员和规则。"""

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, NotAuthenticated, NotFound, PermissionDenied

from core.models import Project, ProjectMember

AI_ACTIONS = {
    "reading": "文献阅读",
    "comparison": "文献比较",
    "review": "原稿诊断",
    "expression": "表达建议",
    "feedback": "反馈拆解",
}


class VersionConflict(APIException):
    status_code = 409
    default_detail = "版本已更新，请重新加载后再提交。"


def require_active_user(user):
    if (
        not user.is_authenticated
        or not get_user_model().objects.filter(pk=user.pk, is_active=True).exists()
    ):
        raise NotAuthenticated("请先登录。")


def visible_projects(user):
    require_active_user(user)
    return Project.objects.filter(Q(owner=user) | Q(members__user=user)).distinct()


def project_role(user, project):
    if project.owner_id == user.pk:
        return ProjectMember.Role.AUTHOR
    return (
        ProjectMember.objects.filter(project=project, user=user)
        .values_list("role", flat=True)
        .first()
    )


def require_project(user, project_id, *, write=False, owner=False, lock=False):
    """写入者在 atomic 中传 lock=True，成员撤权也获取同一项目行锁。"""
    require_active_user(user)
    projects = Project.objects.select_for_update() if lock else Project.objects.all()
    project = projects.filter(pk=project_id).first()
    role = project_role(user, project) if project is not None else None
    if role is None:
        # 不透露其他项目是否存在。
        raise NotFound("项目不存在。")
    if owner and project.owner_id != user.pk:
        raise PermissionDenied("仅项目创建者可以管理成员。")
    if write and role != ProjectMember.Role.AUTHOR:
        raise PermissionDenied("审阅者仅可查看项目。")
    return project


def require_project_resource(user, project_id, queryset, resource_id, *, write=False, lock=False):
    """文件、任务等后续接口必须同时限定 URL 项目和资源自身的 project_id。"""
    project = require_project(user, project_id, write=write, lock=lock)
    return get_object_or_404(queryset, pk=resource_id, project_id=project.pk)


def require_ai_action(user, project_id, action, policy_version, *, lock=False):
    """任务入口、工具调用和发布结果分别调用；通过检查不构成持久授权。"""
    project = require_project(user, project_id, write=True, lock=lock)
    policy = project.policies.order_by("-version").first()
    if policy is None or policy.version != policy_version:
        raise VersionConflict("项目规则已更新，请重新核对。")
    if action not in AI_ACTIONS or not policy.verified or action not in policy.allowed_actions:
        raise PermissionDenied("当前项目规则未允许此 AI 功能。")
    return policy


def check_version(project, version):
    if project.version != version:
        raise VersionConflict()


def advance_version(project):
    project.version += 1
    project.save()
