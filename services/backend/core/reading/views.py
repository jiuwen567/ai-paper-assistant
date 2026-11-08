from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.ai.configuration import model_configuration
from core.ai.sources import sources_snapshot
from core.common.api import paginated, validated
from core.common.errors import ParseFailure
from core.common.serializers import StrictSerializer
from core.jobs.serializers import JobSerializer
from core.jobs.service import dispatch
from core.library.service import searchable_chunks
from core.models import BibliographyRevision, Job, MaterialVersion, ReadingRecord, ReadingRevision
from core.projects.access import VersionConflict, require_ai_action, require_project
from core.reading.service import FIELDS


class ReadingTaskInput(StrictSerializer):
    idempotency_key = serializers.CharField(max_length=128)
    policy_version = serializers.IntegerField(min_value=1)
    purpose = serializers.ChoiceField(choices=["reading", "comparison"])
    question = serializers.CharField(
        max_length=500, default="整理研究对象、方法、结果、局限、实验条件与适用范围。"
    )
    version_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=5)

    def validate(self, data):
        ids = data["version_ids"]
        if (
            len(ids) != len(set(ids))
            or (data["purpose"] == "reading" and len(ids) != 1)
            or (data["purpose"] == "comparison" and len(ids) < 2)
        ):
            raise ValidationError("单篇阅读选择一个版本，多篇比较选择 2–5 个不同版本。")
        return data


class ReadingTaskView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(ReadingTaskInput, request)
        require_ai_action(request.user, project_id, data["purpose"], data["policy_version"])
        data["version_ids"] = sorted(str(pk) for pk in data["version_ids"])
        existing = project.jobs.filter(
            created_by=request.user, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if (
                existing.kind != "ai"
                or existing.policy_version != data["policy_version"]
                or any(
                    existing.input_snapshot.get(key) != data[key]
                    for key in ["purpose", "question", "version_ids"]
                )
            ):
                raise VersionConflict("请求键已用于不同任务。")
            return Response(JobSerializer(existing).data)
        try:
            config = model_configuration(data["purpose"])
            sources = sources_snapshot(project.pk, data["version_ids"])
        except ParseFailure as error:
            return Response({"code": error.code, "detail": error.message}, status=400)
        job = Job.objects.create(
            project=project,
            created_by=request.user,
            kind="ai",
            ai_action=data["purpose"],
            policy_version=data["policy_version"],
            idempotency_key=data["idempotency_key"],
            input_snapshot={
                **{key: data[key] for key in ["purpose", "question", "version_ids"]},
                "sources": sources,
                "model": config,
            },
        )
        transaction.on_commit(lambda: dispatch(job.pk))
        return Response(JobSerializer(job).data, status=201)


def unchanged(record):
    try:
        return (
            sources_snapshot(record.job.project_id, record.job.input_snapshot["version_ids"])
            == record.job.input_snapshot["sources"]
        )
    except ParseFailure:
        return False


class ReadingRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadingRevision
        fields = ["number", "edits", "note", "verified", "created_by", "created_at"]


class ReadingSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(read_only=True)
    purpose = serializers.CharField(source="job.ai_action", read_only=True)
    question = serializers.CharField(source="job.input_snapshot.question", read_only=True)
    author_revision = serializers.SerializerMethodField()
    sources_changed = serializers.SerializerMethodField()

    def get_author_revision(self, record):
        revision = record.revisions.order_by("-number").first()
        return ReadingRevisionSerializer(revision).data if revision else None

    def get_sources_changed(self, record):
        return not unchanged(record)

    class Meta:
        model = ReadingRecord
        fields = [
            "id",
            "job_id",
            "purpose",
            "question",
            "model_output",
            "revision",
            "author_revision",
            "sources_changed",
            "created_at",
        ]


class ReadingListView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        return paginated(
            ReadingRecord.objects.filter(job__project_id=project_id, job__status="succeeded")
            .select_related("job")
            .order_by("-created_at", "id"),
            ReadingSerializer,
            request,
        )


class AuthorEdit(StrictSerializer):
    version_id = serializers.UUIDField()
    field = serializers.ChoiceField(choices=FIELDS)
    text = serializers.CharField(max_length=2000)


class RevisionInput(StrictSerializer):
    version = serializers.IntegerField(min_value=0)
    edits = AuthorEdit(many=True)
    note = serializers.CharField(max_length=5000, allow_blank=True)
    verified = serializers.BooleanField()

    def validate_edits(self, edits):
        keys = [(str(edit["version_id"]), edit["field"]) for edit in edits]
        if len(edits) > 30 or len(keys) != len(set(keys)):
            raise ValidationError("作者修订项重复或超过上限。")
        return [{**edit, "version_id": str(edit["version_id"])} for edit in edits]


class ReadingDetailView(APIView):
    def get(self, request, project_id, record_id):
        require_project(request.user, project_id)
        record = get_object_or_404(
            ReadingRecord.objects.select_related("job"),
            pk=record_id,
            job__project_id=project_id,
            job__status="succeeded",
        )
        return Response(ReadingSerializer(record).data)

    @transaction.atomic
    def patch(self, request, project_id, record_id):
        require_project(request.user, project_id, write=True, lock=True)
        record = get_object_or_404(
            ReadingRecord.objects.select_related("job").select_for_update(),
            pk=record_id,
            job__project_id=project_id,
            job__status="succeeded",
        )
        data = validated(RevisionInput, request)
        if any(
            edit["version_id"] not in record.job.input_snapshot["version_ids"]
            for edit in data["edits"]
        ):
            raise ValidationError("作者修订不能关联其他资料。")
        if data["verified"] and not unchanged(record):
            raise VersionConflict("资料或题录已有变化，请重新阅读后核对。")
        latest = record.revisions.order_by("-number").first()
        values = {key: data[key] for key in ["edits", "note", "verified"]}
        if record.revision != data["version"]:
            if (
                latest
                and latest.number == data["version"] + 1
                and all(getattr(latest, key) == value for key, value in values.items())
            ):
                return Response(ReadingSerializer(record).data)
            raise VersionConflict("阅读结果已被修改，请重新加载。")
        record.revision += 1
        record.save()
        ReadingRevision.objects.create(
            record=record, number=record.revision, created_by=request.user, **values
        )
        return Response(ReadingSerializer(record).data)


class ReadingSourceSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="material.title", read_only=True)
    source_scope = serializers.SerializerMethodField()

    def get_source_scope(self, source):
        revision = (
            BibliographyRevision.objects.filter(bibliography__source_version=source)
            .order_by("-number")
            .first()
        )
        return revision.snapshot["source_scope"] if revision else "unknown"

    class Meta:
        model = MaterialVersion
        fields = ["id", "title", "file_name", "number", "source_scope"]


class ReadingSourceView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        ids = searchable_chunks(project_id).values("run__source_version_id")
        return paginated(
            MaterialVersion.objects.filter(pk__in=ids)
            .select_related("material")
            .order_by("-created_at", "id"),
            ReadingSourceSerializer,
            request,
        )
