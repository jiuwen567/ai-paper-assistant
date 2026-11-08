from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.common.api import paginated, validated
from core.models import ProjectMember, ProjectPolicy
from core.projects.access import (
    advance_version,
    check_version,
    require_ai_action,
    require_project,
    visible_projects,
)
from core.projects.serializers import (
    AIActionSerializer,
    MemberInputSerializer,
    MemberSerializer,
    PolicyInputSerializer,
    PolicySerializer,
    ProjectInputSerializer,
    ProjectSerializer,
    VersionSerializer,
)


def project_response(project, request, status=200):
    return Response(ProjectSerializer(project, context={"request": request}).data, status=status)


class ProjectListView(APIView):
    def get(self, request):
        return paginated(
            visible_projects(request.user).select_related("owner").order_by("-updated_at", "id"),
            ProjectSerializer,
            request,
        )

    @transaction.atomic
    def post(self, request):
        serializer = ProjectInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.save(owner=request.user)
        ProjectPolicy.objects.create(project=project, version=1, created_by=request.user)
        return project_response(project, request, status=201)


class ProjectDetailView(APIView):
    def get(self, request, project_id):
        return project_response(require_project(request.user, project_id), request)

    @transaction.atomic
    def patch(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        check_version(project, validated(VersionSerializer, request)["version"])
        data = validated(ProjectInputSerializer, request, partial=True)
        for key, value in data.items():
            setattr(project, key, value)
        advance_version(project)
        return project_response(project, request)


class PolicyListView(APIView):
    def get(self, request, project_id):
        project = require_project(request.user, project_id)
        return paginated(project.policies.order_by("-version"), PolicySerializer, request)

    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(PolicyInputSerializer, request)
        check_version(project, data.pop("version"))
        latest = project.policies.order_by("-version").first()
        ProjectPolicy.objects.create(
            project=project, version=latest.version + 1, created_by=request.user, **data
        )
        advance_version(project)
        return project_response(project, request, status=201)


class MemberListView(APIView):
    def get(self, request, project_id):
        project = require_project(request.user, project_id)
        return paginated(
            project.members.select_related("user").order_by("id"), MemberSerializer, request
        )

    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, owner=True, lock=True)
        data = validated(MemberInputSerializer, request)
        check_version(project, data["version"])
        user = get_user_model().objects.filter(username=data["username"], is_active=True).first()
        if user is None:
            raise ValidationError("找不到可添加的账号，请核对用户名。")
        if user.pk == project.owner_id:
            raise ValidationError("项目创建者始终保留作者权限。")
        ProjectMember.objects.update_or_create(
            project=project, user=user, defaults={"role": data["role"]}
        )
        advance_version(project)
        return project_response(project, request)


class MemberDetailView(APIView):
    @transaction.atomic
    def delete(self, request, project_id, user_id):
        project = require_project(request.user, project_id, owner=True, lock=True)
        check_version(project, validated(VersionSerializer, request)["version"])
        get_object_or_404(ProjectMember, project=project, user_id=user_id).delete()
        advance_version(project)
        return project_response(project, request)


class AIPermissionView(APIView):
    def post(self, request, project_id):
        data = validated(AIActionSerializer, request)
        policy = require_ai_action(request.user, project_id, **data)
        return Response({"allowed": True, "policy_version": policy.version})
