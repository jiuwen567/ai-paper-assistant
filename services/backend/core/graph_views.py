from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_project
from core.graph import dispatch, graph_paths, mark_dirty, path_records
from core.models import ContentBlock, GraphEvent, GraphState, Material
from core.projects import validated
from core.reading import StrictSerializer


class PathInput(StrictSerializer):
    block_id = serializers.UUIDField(required=False)
    material_id = serializers.UUIDField(required=False)
    page = serializers.IntegerField(min_value=1, default=1)


class RebuildInput(StrictSerializer):
    request_key = serializers.CharField(max_length=128)
    revision = serializers.IntegerField(min_value=0)


def graph_state(state):
    return {
        "revision": state.revision,
        "applied_revision": state.applied_revision,
        "error_code": state.last_error,
        "pending_events": GraphEvent.objects.filter(
            project_id=state.project_id, processed_at=None
        ).count(),
    }


class GraphPathsView(APIView):
    @transaction.atomic
    def get(self, request, project_id):
        require_project(request.user, project_id, lock=True)
        query = PathInput(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        if data.get("block_id"):
            get_object_or_404(ContentBlock, pk=data["block_id"], manuscript__project_id=project_id)
        if data.get("material_id"):
            get_object_or_404(Material, pk=data["material_id"], project_id=project_id)
        state = GraphState.objects.select_for_update().get(project_id=project_id)
        result = {
            **graph_state(state),
            "status": "pending",
            "count": None,
            "results": [],
            "page": data["page"],
            "next": False,
            "previous": data["page"] > 1,
        }
        try:
            revision, ids, count = graph_paths(
                project_id,
                block_id=data.get("block_id"),
                material_id=data.get("material_id"),
                offset=(data["page"] - 1) * 20,
            )
            result["projected_revision"] = revision
            if revision is None:
                result["status"] = "missing"
            elif revision > state.revision:
                result["status"] = "inconsistent"
            elif revision != state.revision:
                result["status"] = "pending"
            else:
                records = {item["id"]: item for item in path_records(project_id, ids)}
                if set(ids) != set(records) or any(
                    (data.get("block_id") and item["block_id"] != str(data["block_id"]))
                    or (data.get("material_id") and item["material_id"] != str(data["material_id"]))
                    for item in records.values()
                ):
                    result["status"] = "inconsistent"
                else:
                    result.update(
                        status="synced",
                        count=count,
                        results=[records[pk] for pk in ids],
                        next=data["page"] * 20 < count,
                    )
        except Exception as error:
            result["status"] = "unavailable"
            result["error_code"] = ("query_" + type(error).__name__)[:100]
        return Response(result)


class GraphRebuildView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        require_project(request.user, project_id, write=True, lock=True)
        data = validated(RebuildInput, request)
        state = GraphState.objects.select_for_update().get(project_id=project_id)
        previous = GraphEvent.objects.filter(
            project_id=project_id, request_key=data["request_key"]
        ).first()
        if previous:
            if (
                previous.created_by_id != request.user.pk
                or previous.requested_revision != data["revision"]
            ):
                raise VersionConflict("请求键已用于其他图重建请求。")
            return Response(graph_state(state))
        if state.revision != data["revision"]:
            raise VersionConflict("业务关系已有新版本，请刷新图状态后重试。")
        # 从较旧 PostgreSQL 备份恢复后，显式重建仍须越过现存图水位，
        # 不能用强制覆盖绕开乱序保护。图暂时不可用时先保留普通重建事件。
        try:
            projected, _, _ = graph_paths(project_id, limit=0)
        except Exception:
            projected = None
        if projected is not None and projected > state.revision:
            GraphState.objects.filter(project_id=project_id).update(revision=projected)
        revision = mark_dirty(project_id)
        GraphEvent.objects.filter(project_id=project_id, revision=revision).update(
            request_key=data["request_key"],
            requested_revision=data["revision"],
            created_by=request.user,
        )
        state.refresh_from_db()
        transaction.on_commit(dispatch)
        return Response(graph_state(state), status=202)
