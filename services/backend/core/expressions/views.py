from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.ai.configuration import model_configuration
from core.ai.sources import sources_snapshot
from core.common.api import paginated, validated
from core.common.digests import digest
from core.common.errors import ParseFailure
from core.common.serializers import StrictSerializer
from core.expressions.service import (
    citation_snapshot,
    content_guards,
    copy_citations,
    input_changed,
    text_diff,
)
from core.jobs.serializers import JobSerializer
from core.jobs.service import dispatch
from core.manuscripts.service import prepare_write, publish, revision_data
from core.models import ExpressionDecision, ExpressionSuggestion, Job
from core.projects.access import VersionConflict, require_ai_action, require_project
from core.reviews.service import manuscript_snapshot


class ExpressionTaskInput(StrictSerializer):
    idempotency_key = serializers.CharField(max_length=128)
    policy_version = serializers.IntegerField(min_value=1)
    manuscript_version = serializers.IntegerField(min_value=1, max_value=2147483647)
    block_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=20)
    version_ids = serializers.ListField(child=serializers.UUIDField(), max_length=5)
    question = serializers.CharField(max_length=500, default="改善已有文字的表达，保持原意和依据。")

    def validate(self, data):
        for key in ["block_ids", "version_ids"]:
            if len(data[key]) != len(set(data[key])):
                raise ValidationError("选择范围不能重复。")
            data[key] = sorted(str(value) for value in data[key])
        return data


class ExpressionTaskView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(ExpressionTaskInput, request)
        require_ai_action(request.user, project_id, "expression", data["policy_version"])
        keys = ["manuscript_version", "block_ids", "version_ids", "question"]
        existing = project.jobs.filter(
            created_by=request.user, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if (
                existing.ai_action != "expression"
                or existing.kind != "ai"
                or existing.policy_version != data["policy_version"]
                or any(existing.input_snapshot.get(key) != data[key] for key in keys)
            ):
                raise VersionConflict("请求键已用于不同任务。")
            return Response(JobSerializer(existing).data)
        try:
            model = model_configuration("expression")
            manuscript = manuscript_snapshot(
                project_id, data["manuscript_version"], data["block_ids"]
            )
            sources = sources_snapshot(project_id, data["version_ids"], allow_empty=True)
            citations = citation_snapshot(
                project_id, [item["version_id"] for item in manuscript["blocks"]]
            )
        except ParseFailure as error:
            return Response(
                {"code": error.code, "detail": error.message},
                status=400 if error.code == "model_unconfigured" else 409,
            )
        job = Job.objects.create(
            project=project,
            created_by=request.user,
            kind="ai",
            ai_action="expression",
            policy_version=data["policy_version"],
            idempotency_key=data["idempotency_key"],
            input_snapshot={
                **{key: data[key] for key in keys},
                "purpose": "expression",
                "model": model,
                "manuscript": manuscript,
                "sources": sources,
                "citation_ids": citations,
            },
        )
        transaction.on_commit(lambda: dispatch(job.pk))
        return Response(JobSerializer(job).data, status=201)


class DecisionSerializer(serializers.ModelSerializer):
    manuscript_version = serializers.IntegerField(source="manuscript_revision.number", default=None)

    class Meta:
        model = ExpressionDecision
        fields = [
            "action",
            "text",
            "reason",
            "meaning_confirmed",
            "policy_version",
            "manuscript_version",
            "created_by",
            "created_at",
        ]


class SuggestionSerializer(serializers.ModelSerializer):
    manuscript_version = serializers.IntegerField(source="manuscript_revision.number")
    manuscript_text = serializers.CharField(source="block_version.text")
    input_changed = serializers.SerializerMethodField()
    decision = DecisionSerializer(read_only=True)
    diff = serializers.SerializerMethodField()
    job_id = serializers.UUIDField()

    def get_input_changed(self, suggestion):
        return input_changed(suggestion.job)

    def get_diff(self, suggestion):
        value = suggestion.model_output
        return text_diff(value["quote"], value["replacement"])

    class Meta:
        model = ExpressionSuggestion
        fields = [
            "id",
            "job_id",
            "manuscript_version",
            "manuscript_text",
            "model_output",
            "input_changed",
            "diff",
            "decision",
            "created_at",
        ]


def suggestions(project_id):
    return ExpressionSuggestion.objects.filter(
        job__project_id=project_id, job__status="succeeded"
    ).select_related("job", "block_version", "manuscript_revision", "decision__manuscript_revision")


class SuggestionListView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        query = suggestions(project_id)
        state = request.query_params.get("state")
        if state == "pending":
            query = query.filter(decision__isnull=True)
        elif state in ["accepted", "edited", "rejected"]:
            query = query.filter(decision__action=state)
        elif state:
            raise ValidationError("建议筛选条件无效。")
        return paginated(query.order_by("-created_at", "id"), SuggestionSerializer, request)


class SuggestionDetailView(APIView):
    def get(self, request, project_id, suggestion_id):
        require_project(request.user, project_id)
        return Response(
            SuggestionSerializer(get_object_or_404(suggestions(project_id), pk=suggestion_id)).data
        )


class DecideInput(StrictSerializer):
    request_key = serializers.CharField(max_length=128)
    manuscript_version = serializers.IntegerField(min_value=1, max_value=2147483647)
    policy_version = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=["accepted", "edited", "rejected"])
    text = serializers.CharField(
        max_length=1200, trim_whitespace=False, default="", allow_blank=True
    )
    reason = serializers.CharField(max_length=2000, default="", allow_blank=True)
    meaning_confirmed = serializers.BooleanField(default=False)

    def validate(self, data):
        if data["action"] == "edited" and not data["text"].strip():
            raise ValidationError("编辑后接受需要填写文字。")
        if data["action"] != "edited" and data["text"]:
            raise ValidationError("只有编辑后接受可以提交新文字。")
        if data["action"] != "rejected" and not data["meaning_confirmed"]:
            raise ValidationError("请先核对原意、数据、条件与依据，再确认只是表达修改。")
        return data


class SuggestionDecisionView(APIView):
    @transaction.atomic
    def post(self, request, project_id, suggestion_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(DecideInput, request)
        policy = project.policies.order_by("-version").first()
        if policy is None or policy.version != data["policy_version"]:
            raise VersionConflict("项目规则已更新，请重新核对。")
        if data["action"] != "rejected":
            require_ai_action(request.user, project_id, "expression", data["policy_version"])
        suggestion = get_object_or_404(suggestions(project_id), pk=suggestion_id)
        request_digest = digest(
            {"project_id": str(project_id), "suggestion_id": str(suggestion_id), **data}
        )
        existing = ExpressionDecision.objects.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.request_digest != request_digest:
                raise VersionConflict("请求键已用于不同决定。")
            return Response(SuggestionSerializer(suggestion).data)
        if hasattr(suggestion, "decision"):
            raise VersionConflict("此建议已被处理，请重新加载。")
        if data["manuscript_version"] != suggestion.manuscript_revision.number:
            raise VersionConflict("提交的原稿版本与建议不符。")
        result = None
        text = ""
        if data["action"] != "rejected":
            if input_changed(suggestion.job):
                raise VersionConflict("原稿或依据已变化，旧建议不能覆盖新稿，请重新生成建议。")
            value = suggestion.model_output
            if value["kind"] != "expression":
                raise ValidationError("涉及实质论证，不能作为表达建议采纳，请在原稿中自行修改。")
            text = data["text"] if data["action"] == "edited" else value["replacement"]
            guards = content_guards(value["quote"], text)
            if guards:
                raise ValidationError(guards)
            if text == value["quote"]:
                raise ValidationError("文字没有变化，可拒绝该建议。")
            write = {
                "version": data["manuscript_version"],
                "request_key": "expression:" + request_digest,
            }
            manuscript, old, write_digest = prepare_write(
                project, request.user, write, "expression"
            )
            if old:
                raise VersionConflict("原稿操作已存在，请重新加载决定。")
            current = revision_data(manuscript.current_revision)
            blocks = [
                {key: block[key] for key in ["id", "text", "heading_level"]}
                for block in current["blocks"]
            ]
            for block in blocks:
                if block["id"] == str(suggestion.block_version.block_id):
                    original = block["text"]
                    if original[value["start"] : value["end"]] != value["quote"]:
                        raise VersionConflict("原句位置已变化，请重新生成建议。")
                    block["text"] = original[: value["start"]] + text + original[value["end"] :]
                    if len(block["text"]) > 20000:
                        raise ValidationError("修改后正文块超过 2 万字符。")
            result = publish(
                manuscript,
                request.user,
                write,
                write_digest,
                current["research"],
                blocks,
                origin="expression",
                source={"suggestion_id": str(suggestion.pk)},
            )
            after = result.items.get(block_id=suggestion.block_version.block_id).block_version
            copy_citations(request.user, suggestion.block_version, after, value["citations"])
        ExpressionDecision.objects.create(
            suggestion=suggestion,
            action=data["action"],
            text=text,
            reason=data["reason"],
            meaning_confirmed=data["meaning_confirmed"],
            policy_version=data["policy_version"],
            manuscript_revision=result,
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=request_digest,
        )
        return Response(SuggestionSerializer(suggestions(project_id).get(pk=suggestion_id)).data)


class PreviewInput(StrictSerializer):
    text = serializers.CharField(max_length=1200, trim_whitespace=False)


class SuggestionPreviewView(APIView):
    def post(self, request, project_id, suggestion_id):
        require_project(request.user, project_id)
        suggestion = get_object_or_404(suggestions(project_id), pk=suggestion_id)
        data = validated(PreviewInput, request)
        value = suggestion.model_output
        guards = content_guards(value["quote"], data["text"])
        if value["kind"] != "expression":
            guards.append("涉及实质论证，请由作者在原稿中处理。")
        return Response({"diff": text_diff(value["quote"], data["text"]), "guard_reasons": guards})
