from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_project
from core.ai_jobs import digest
from core.disclosures import draft_for, facts_for, job_data, pick, usage_jobs
from core.models import DisclosureRevision
from core.projects import paginated, validated
from core.reading import StrictSerializer


class ExternalUse(StrictSerializer):
    tool = serializers.CharField(max_length=200)
    purpose = serializers.CharField(max_length=1000)
    scope = serializers.CharField(max_length=1000)
    used_at = serializers.CharField(max_length=100, allow_blank=True)
    note = serializers.CharField(max_length=2000, allow_blank=True)


class DisclosureInput(StrictSerializer):
    version = serializers.IntegerField(min_value=0)
    request_key = serializers.CharField(max_length=128)
    facts_token = serializers.RegexField(r"^[a-f0-9]{64}$")
    text = serializers.CharField(max_length=20000, allow_blank=True)
    external_uses = ExternalUse(many=True, max_length=50)
    verified = serializers.BooleanField()

    def validate(self, data):
        if data["verified"] and not data["text"].strip():
            raise ValidationError("核对清单前请填写使用说明。")
        return data


class DisclosureSerializer(serializers.ModelSerializer):
    class Meta:
        model = DisclosureRevision
        fields = [
            "number",
            "text",
            "external_uses",
            "verified",
            "facts_token",
            "created_by",
            "created_at",
        ]


def state(project, facts=None):
    facts = facts if facts is not None else facts_for(project)
    token = digest(facts)
    latest = project.disclosures.order_by("-number").first()
    return {
        "summary": facts["summary"],
        "purposes": facts["purposes"],
        "manuscript_version": facts["manuscript_version"],
        "facts_token": token,
        "draft": draft_for(facts),
        "current": DisclosureSerializer(latest).data if latest else None,
        "stale": bool(latest and latest.facts_token != token),
    }


class DisclosureView(APIView):
    @transaction.atomic
    def get(self, request, project_id):
        project = require_project(request.user, project_id, lock=True)
        return Response(state(project))

    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(DisclosureInput, request)
        fingerprint = digest(data)
        existing = project.disclosures.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.request_digest != fingerprint:
                raise VersionConflict("请求键已用于不同的披露清单。")
            return Response({**state(project), "saved_number": existing.number})
        latest = project.disclosures.order_by("-number").first()
        version = latest.number if latest else 0
        if data["version"] != version:
            raise VersionConflict("披露清单已有新版本，请刷新记录后核对，保留当前草稿。")
        facts = facts_for(project)
        if data["facts_token"] != digest(facts):
            raise VersionConflict("使用记录或稿件已有变化，请刷新记录后重新核对。")
        saved = DisclosureRevision.objects.create(
            project=project,
            number=version + 1,
            created_by=request.user,
            facts=facts,
            request_digest=fingerprint,
            **pick(data, ["request_key", "facts_token", "text", "external_uses", "verified"]),
        )
        return Response({**state(project, facts), "saved_number": saved.number}, status=201)


class DisclosureHistoryView(APIView):
    def get(self, request, project_id):
        project = require_project(request.user, project_id)
        return paginated(project.disclosures.order_by("-number"), DisclosureSerializer, request)


class DisclosureRevisionView(APIView):
    def get(self, request, project_id, number):
        project = require_project(request.user, project_id)
        revision = get_object_or_404(project.disclosures, number=number)
        return Response({**DisclosureSerializer(revision).data, "facts": revision.facts})


class UsageSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        return job_data(instance)


class UsageListView(APIView):
    @transaction.atomic
    def get(self, request, project_id):
        require_project(request.user, project_id, lock=True)
        return paginated(
            usage_jobs(project_id).order_by("-created_at", "id"), UsageSerializer, request
        )


class UsageDetailView(APIView):
    @transaction.atomic
    def get(self, request, project_id, job_id):
        require_project(request.user, project_id, lock=True)
        job = get_object_or_404(usage_jobs(project_id), pk=job_id)
        sources = job.input_snapshot.get("sources", [])
        return Response(
            {
                **job_data(job),
                "sources": [
                    pick(
                        source,
                        [
                            "chunk_id",
                            "id",
                            "parse_id",
                            "source_version_id",
                            "bibliography_revision_id",
                            "source_scope",
                            "state_version",
                        ],
                    )
                    for source in sources
                ],
            }
        )
