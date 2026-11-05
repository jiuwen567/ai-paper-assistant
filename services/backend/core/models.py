import uuid

from django.conf import settings
from django.db import models
from pgvector.django import VectorField


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    paper_type = models.CharField(max_length=80, blank=True)
    requirements = models.TextField(blank=True)
    template = models.CharField(max_length=120, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProjectMember(models.Model):
    class Role(models.TextChoices):
        AUTHOR = "author", "作者"
        REVIEWER = "reviewer", "审阅者"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="unique_project_member"),
            models.CheckConstraint(
                condition=models.Q(role__in=["author", "reviewer"]), name="valid_project_role"
            ),
        ]


class ProjectPolicy(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="policies")
    version = models.PositiveIntegerField()
    source = models.CharField(max_length=500, blank=True)
    source_version = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    allowed_actions = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "version"], name="unique_project_policy"),
            models.CheckConstraint(
                condition=models.Q(verified=True) | models.Q(allowed_actions=[]),
                name="unverified_policy_disables_ai",
            ),
            models.CheckConstraint(
                condition=models.Q(verified=False)
                | (~models.Q(source="") & ~models.Q(source_version="")),
                name="verified_policy_has_source",
            ),
        ]


class DisclosureRevision(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="disclosures")
    number = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    external_uses = models.JSONField(default=list)
    verified = models.BooleanField(default=False)
    facts = models.JSONField()
    facts_token = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "number"], name="unique_disclosure_revision"
            ),
            models.UniqueConstraint(
                fields=["project", "created_by", "request_key"], name="unique_disclosure_request"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="disclosure_positive_revision"
            ),
        ]


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "等待执行"
        RUNNING = "running", "执行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="jobs")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=40)
    idempotency_key = models.CharField(max_length=128)
    input_snapshot = models.JSONField(default=dict)
    ai_action = models.CharField(max_length=32, blank=True)
    policy_version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    generation = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    progress = models.PositiveSmallIntegerField(default=0)
    retryable = models.BooleanField(default=False)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=300, blank=True)
    output = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "idempotency_key"], name="unique_job_request"
            ),
            models.CheckConstraint(
                condition=models.Q(progress__lte=100), name="job_progress_range"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["queued", "running", "succeeded", "failed", "cancelled"]
                ),
                name="job_valid_status",
            ),
        ]
        indexes = [models.Index(fields=["status", "lease_until"])]


class JobAttempt(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="attempts")
    generation = models.PositiveIntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=16, choices=Job.Status.choices, default=Job.Status.RUNNING)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "generation"], name="unique_job_attempt")
        ]


class ModelCall(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="model_calls")
    generation = models.PositiveIntegerField()
    number = models.PositiveIntegerField()
    model = models.CharField(max_length=128)
    prompt_version = models.CharField(max_length=64)
    input_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default="running")
    usage = models.JSONField(null=True)
    elapsed_ms = models.PositiveIntegerField(null=True)
    error_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "generation", "number"], name="unique_model_call"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1, number__lte=4), name="model_call_limit"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["running", "succeeded", "failed", "cancelled"]),
                name="model_call_status",
            ),
        ]


class AIEvent(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="ai_events")
    generation = models.PositiveIntegerField()
    kind = models.CharField(max_length=32)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class ReadingRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="reading_record")
    model_output = models.JSONField()
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class ReadingRevision(models.Model):
    record = models.ForeignKey(ReadingRecord, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    edits = models.JSONField(default=list)
    note = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["record", "number"], name="unique_reading_revision"),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="reading_positive_revision"
            ),
        ]


class Manuscript(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="manuscript")
    current_revision = models.ForeignKey(
        "ManuscriptRevision", null=True, on_delete=models.SET_NULL, related_name="+"
    )


class ContentBlock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manuscript = models.ForeignKey(Manuscript, on_delete=models.CASCADE, related_name="blocks")
    imported_from = models.ForeignKey(
        "MaterialVersion", null=True, on_delete=models.CASCADE, related_name="imported_blocks"
    )


class BlockVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    block = models.ForeignKey(ContentBlock, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    text = models.TextField()
    heading_level = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["block", "number"], name="unique_block_version"),
            models.CheckConstraint(condition=models.Q(number__gt=0), name="block_version_positive"),
            models.CheckConstraint(
                condition=models.Q(heading_level__lte=9), name="block_heading_level"
            ),
        ]


class ManuscriptRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manuscript = models.ForeignKey(Manuscript, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    research = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)
    origin = models.CharField(max_length=16, default="edit")
    source = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manuscript", "number"], name="unique_manuscript_revision"
            ),
            models.UniqueConstraint(
                fields=["manuscript", "created_by", "request_key"], name="unique_manuscript_request"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="manuscript_revision_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    origin__in=["edit", "import", "restore", "expression", "cleanup"]
                ),
                name="manuscript_revision_origin",
            ),
        ]


class RevisionBlock(models.Model):
    revision = models.ForeignKey(ManuscriptRevision, on_delete=models.CASCADE, related_name="items")
    block = models.ForeignKey(ContentBlock, on_delete=models.CASCADE)
    block_version = models.ForeignKey(BlockVersion, on_delete=models.RESTRICT)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "position"], name="unique_revision_position"
            ),
            models.UniqueConstraint(fields=["revision", "block"], name="unique_revision_block"),
        ]


class ReviewRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="review_record")
    manuscript_revision = models.ForeignKey(ManuscriptRevision, on_delete=models.RESTRICT)
    previous_review = models.ForeignKey(
        "self", null=True, on_delete=models.RESTRICT, related_name="rechecks"
    )
    summary = models.TextField()
    source_checks = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)


class ReviewFinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(ReviewRecord, on_delete=models.CASCADE, related_name="findings")
    block_version = models.ForeignKey(BlockVersion, on_delete=models.RESTRICT)
    category = models.CharField(max_length=32)
    model_output = models.JSONField()
    status = models.CharField(max_length=16, default="pending")
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "confirmed", "ignored"]),
                name="review_finding_status",
            )
        ]


class ReviewDecision(models.Model):
    finding = models.ForeignKey(ReviewFinding, on_delete=models.CASCADE, related_name="decisions")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=16)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["finding", "number"], name="unique_review_decision"),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="review_decision_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "confirmed", "ignored"]),
                name="review_decision_status",
            ),
        ]


class ExpressionSuggestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="expression_suggestions")
    manuscript_revision = models.ForeignKey(ManuscriptRevision, on_delete=models.RESTRICT)
    block_version = models.ForeignKey(BlockVersion, on_delete=models.RESTRICT)
    model_output = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class ExpressionDecision(models.Model):
    suggestion = models.OneToOneField(
        ExpressionSuggestion, on_delete=models.CASCADE, related_name="decision"
    )
    action = models.CharField(max_length=16)
    text = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    meaning_confirmed = models.BooleanField(default=False)
    policy_version = models.PositiveIntegerField()
    manuscript_revision = models.ForeignKey(
        ManuscriptRevision, null=True, on_delete=models.RESTRICT
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_expression_decision_request"
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=["accepted", "edited", "rejected"]),
                name="expression_decision_action",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(action="rejected", manuscript_revision__isnull=True)
                    | models.Q(
                        action__in=["accepted", "edited"],
                        manuscript_revision__isnull=False,
                        meaning_confirmed=True,
                    )
                ),
                name="expression_decision_result",
            ),
        ]


class ManuscriptCitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    block_version = models.ForeignKey(
        BlockVersion, on_delete=models.CASCADE, related_name="citations"
    )
    chunk = models.ForeignKey("SourceChunk", on_delete=models.RESTRICT)
    bibliography_revision = models.ForeignKey(
        "BibliographyRevision", null=True, on_delete=models.RESTRICT
    )
    snapshot = models.JSONField()
    fingerprint = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["block_version", "fingerprint"], name="unique_manuscript_citation"
            ),
        ]


class WechatIdentity(models.Model):
    app_id = models.CharField(max_length=64)
    open_id = models.CharField(max_length=128)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    bound_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["app_id", "open_id"], name="unique_wechat_identity"),
            models.UniqueConstraint(fields=["app_id", "user"], name="unique_user_wechat_app"),
        ]


class WechatBinding(models.Model):
    identity = models.ForeignKey(WechatIdentity, on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)


class WechatSession(models.Model):
    identity = models.ForeignKey(WechatIdentity, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)


class Material(models.Model):
    access_state = models.CharField(max_length=16, default="active")
    state_version = models.PositiveIntegerField(default=1)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="materials")
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=24)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(access_state__in=["active", "withdrawn"]),
                name="material_access_state",
            ),
            models.CheckConstraint(
                condition=models.Q(state_version__gt=0), name="material_positive_state_version"
            ),
        ]


class MaterialVersion(models.Model):
    class Status(models.TextChoices):
        UPLOADING = "uploading", "等待上传"
        VALIDATING = "validating", "上传校验中"
        AVAILABLE = "available", "可用"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=128)
    request_snapshot = models.JSONField()
    file_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64, blank=True)
    bucket = models.CharField(max_length=100)
    object_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADING)
    usage_state = models.CharField(max_length=16, default="active")
    usage_version = models.PositiveIntegerField(default=1)
    generation = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["material", "number"], name="unique_material_version"),
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_upload_request"
            ),
            models.CheckConstraint(condition=models.Q(size__gt=0), name="material_nonempty_file"),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="material_positive_version"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["uploading", "validating", "available", "failed"]),
                name="material_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(usage_state__in=["active", "corrected", "withdrawn"]),
                name="material_version_usage_state",
            ),
            models.CheckConstraint(
                condition=models.Q(usage_version__gt=0), name="material_usage_version_positive"
            ),
        ]


class ParseRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_version = models.ForeignKey(
        MaterialVersion, on_delete=models.CASCADE, related_name="parses"
    )
    number = models.PositiveIntegerField()
    parser_version = models.CharField(max_length=128)
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="parse_run")
    warnings = models.JSONField(default=list)
    coverage = models.CharField(max_length=16, default="pending")
    published_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_version", "number"], name="unique_parse_version"
            ),
            models.CheckConstraint(condition=models.Q(number__gt=0), name="parse_positive_version"),
        ]


class SourceChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(ParseRun, on_delete=models.CASCADE, related_name="chunks")
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    anchor = models.JSONField()
    heading_level = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "ordinal"], name="unique_source_chunk"),
            models.CheckConstraint(
                condition=models.Q(ordinal__gt=0), name="chunk_positive_ordinal"
            ),
            models.CheckConstraint(
                condition=models.Q(heading_level__lte=9), name="chunk_heading_range"
            ),
        ]


class Bibliography(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_version = models.OneToOneField(
        MaterialVersion, on_delete=models.CASCADE, related_name="bibliography"
    )
    revision = models.PositiveIntegerField(default=0)


class BibliographyRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bibliography = models.ForeignKey(
        Bibliography, on_delete=models.CASCADE, related_name="revisions"
    )
    number = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["bibliography", "number"], name="unique_bibliography_revision"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="bibliography_positive_revision"
            ),
        ]


class EvidenceCard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chunk = models.ForeignKey(SourceChunk, on_delete=models.CASCADE, related_name="evidence_cards")
    bibliography_revision = models.ForeignKey(BibliographyRevision, on_delete=models.RESTRICT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=128)
    request_snapshot = models.JSONField()
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_evidence_request"
            ),
        ]


class EvidenceNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evidence = models.ForeignKey(EvidenceCard, on_delete=models.CASCADE, related_name="notes")
    number = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    tags = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evidence", "number"], name="unique_evidence_note"),
            models.CheckConstraint(condition=models.Q(number__gt=0), name="note_positive_revision"),
        ]


class EmbeddingIndex(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="embedding_index")
    model_name = models.CharField(max_length=128)
    dimension = models.PositiveIntegerField()
    artifact_digest = models.CharField(max_length=64)
    pipeline_version = models.CharField(max_length=64)
    published_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ChunkEmbedding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    index = models.ForeignKey(EmbeddingIndex, on_delete=models.CASCADE, related_name="segments")
    chunk = models.ForeignKey(SourceChunk, on_delete=models.CASCADE, related_name="embeddings")
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    text_sha256 = models.CharField(max_length=64)
    vector = VectorField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["index", "chunk", "start"], name="unique_embedding_segment"
            ),
            models.CheckConstraint(
                condition=models.Q(end__gt=models.F("start")), name="embedding_nonempty_segment"
            ),
        ]


class GraphState(models.Model):
    project = models.OneToOneField(Project, primary_key=True, on_delete=models.CASCADE)
    revision = models.PositiveBigIntegerField(default=0)
    applied_revision = models.PositiveBigIntegerField(default=0)
    last_error = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class GraphTombstone(models.Model):
    # 不外键依赖项目：项目删除后仍须保留可重试的投影清理事件。
    project_id = models.UUIDField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)


class GraphEvent(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="graph_events")
    revision = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=100, blank=True)
    next_attempt_at = models.DateTimeField(null=True)
    request_key = models.CharField(max_length=128, null=True)
    requested_revision = models.PositiveBigIntegerField(null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "revision"], name="unique_graph_event"),
            models.UniqueConstraint(fields=["project", "request_key"], name="unique_graph_rebuild"),
            models.CheckConstraint(condition=models.Q(revision__gt=0), name="graph_event_positive"),
        ]
        indexes = [models.Index(fields=["processed_at", "next_attempt_at"])]


class EvidenceLink(models.Model):
    """固定原稿主张和来源原话；核对决定单独追加，不把模型候选视为作者确认。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="evidence_links")
    manuscript_revision = models.ForeignKey(ManuscriptRevision, on_delete=models.RESTRICT)
    block_version = models.ForeignKey(BlockVersion, on_delete=models.RESTRICT)
    chunk = models.ForeignKey(SourceChunk, on_delete=models.RESTRICT)
    bibliography_revision = models.ForeignKey(
        BibliographyRevision, null=True, on_delete=models.RESTRICT
    )
    claim = models.TextField()
    claim_start = models.PositiveIntegerField()
    evidence_quote = models.TextField()
    evidence_start = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "request_key"], name="unique_evidence_link_request"
            ),
        ]


class EvidenceLinkRevision(models.Model):
    link = models.ForeignKey(EvidenceLink, on_delete=models.CASCADE, related_name="decisions")
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=16)
    kind = models.CharField(max_length=16)
    note = models.TextField(blank=True)
    source_state_version = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["link", "number"], name="unique_evidence_link_version"),
            models.UniqueConstraint(
                fields=["link", "created_by", "request_key"], name="unique_evidence_link_decision"
            ),
            models.CheckConstraint(condition=models.Q(number__gt=0), name="evidence_link_positive"),
            models.CheckConstraint(
                condition=models.Q(state__in=["confirmed", "withdrawn"]),
                name="evidence_link_state",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=["supports", "contradicts", "context"]),
                name="evidence_link_kind",
            ),
        ]


class Feedback(models.Model):
    """首版仅保存作者录入的原始意见，不代表导师本人提交。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="feedback")
    text = models.TextField()
    source_label = models.CharField(max_length=500)
    source_chunk = models.ForeignKey(SourceChunk, null=True, on_delete=models.RESTRICT)
    manuscript_revision = models.ForeignKey(
        ManuscriptRevision, null=True, on_delete=models.RESTRICT
    )
    block_version = models.ForeignKey(BlockVersion, null=True, on_delete=models.RESTRICT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "request_key"], name="unique_feedback_request"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(manuscript_revision__isnull=True, block_version__isnull=True)
                    | models.Q(manuscript_revision__isnull=False, block_version__isnull=False)
                ),
                name="feedback_location_pair",
            ),
        ]


class FeedbackCandidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feedback = models.ForeignKey(Feedback, on_delete=models.CASCADE, related_name="candidates")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="feedback_candidates")
    model_output = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class FeedbackTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feedback = models.ForeignKey(Feedback, on_delete=models.CASCADE, related_name="tasks")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_feedback_task_request"
            )
        ]


class FeedbackCandidateDecision(models.Model):
    candidate = models.OneToOneField(
        FeedbackCandidate, on_delete=models.CASCADE, related_name="decision"
    )
    task = models.OneToOneField(
        FeedbackTask, null=True, on_delete=models.CASCADE, related_name="candidate_decision"
    )
    action = models.CharField(max_length=16)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_feedback_decision_request"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(action="accepted", task__isnull=False)
                    | models.Q(action="rejected", task__isnull=True)
                ),
                name="feedback_decision_result",
            ),
        ]


class FeedbackTaskRevision(models.Model):
    task = models.ForeignKey(FeedbackTask, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    instruction = models.TextField()
    status = models.CharField(max_length=16, default="todo")
    note = models.TextField(blank=True)
    result_kind = models.CharField(max_length=16, default="pending")
    manuscript_revision = models.ForeignKey(
        ManuscriptRevision, null=True, on_delete=models.RESTRICT
    )
    block_version = models.ForeignKey(BlockVersion, null=True, on_delete=models.RESTRICT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "number"], name="unique_feedback_task_revision"
            ),
            models.UniqueConstraint(
                fields=["task", "created_by", "request_key"],
                name="unique_feedback_progress_request",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="feedback_task_positive_revision"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["todo", "doing", "completed", "dropped"]),
                name="feedback_task_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(manuscript_revision__isnull=True, block_version__isnull=True)
                    | models.Q(manuscript_revision__isnull=False, block_version__isnull=False)
                ),
                name="feedback_task_location_pair",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="completed", result_kind="modified", block_version__isnull=False
                    )
                    | models.Q(status="completed", result_kind="no_change")
                    | (~models.Q(status="completed") & models.Q(result_kind="pending"))
                ),
                name="feedback_task_completion",
            ),
        ]


class MentorReport(models.Model):
    """作者转录的导师回复，仅对明确的任务处理版本有效。"""

    revision = models.ForeignKey(
        FeedbackTaskRevision, on_delete=models.CASCADE, related_name="mentor_reports"
    )
    status = models.CharField(max_length=24)
    text = models.TextField()
    source_label = models.CharField(max_length=500)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_mentor_report_request"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["confirmed", "changes_requested"]),
                name="mentor_report_status",
            ),
        ]


class MaterialChange(models.Model):
    """作者明确登记的版本关系；上传本身不改变旧版的使用状态。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_version = models.ForeignKey(
        MaterialVersion, on_delete=models.CASCADE, related_name="changes"
    )
    replacement = models.ForeignKey(
        MaterialVersion, null=True, on_delete=models.RESTRICT, related_name="replaces"
    )
    kind = models.CharField(max_length=16)
    scope = models.CharField(max_length=16, default="version")
    note = models.TextField()
    state_snapshot = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_version", "created_by", "request_key"],
                name="unique_material_change_request",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind__in=["supplement", "correction"],
                        replacement__isnull=False,
                        scope="version",
                    )
                    | models.Q(
                        kind="withdrawal",
                        replacement__isnull=True,
                        scope__in=["version", "material"],
                    )
                ),
                name="material_change_shape",
            ),
            models.CheckConstraint(condition=~models.Q(note=""), name="material_change_note"),
        ]


class ImpactRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change = models.ForeignKey(MaterialChange, on_delete=models.CASCADE, related_name="runs")
    number = models.PositiveIntegerField()
    manuscript_revision = models.ForeignKey(
        ManuscriptRevision, null=True, on_delete=models.RESTRICT
    )
    source_snapshot = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["change", "number"], name="unique_impact_run_number"),
            models.UniqueConstraint(
                fields=["change", "created_by", "request_key"], name="unique_impact_run_request"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="impact_run_number_positive"
            ),
        ]


class ImpactItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(ImpactRun, on_delete=models.CASCADE, related_name="items")
    key = models.CharField(max_length=80)
    origin = models.CharField(max_length=16)
    block_version = models.ForeignKey(BlockVersion, null=True, on_delete=models.RESTRICT)
    suggestion = models.ForeignKey(ExpressionSuggestion, null=True, on_delete=models.CASCADE)
    task = models.ForeignKey(FeedbackTask, null=True, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, null=True, on_delete=models.CASCADE)
    snapshot = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "key"], name="unique_impact_item"),
            models.CheckConstraint(
                condition=(
                    models.Q(origin="registered", job__isnull=True)
                    | models.Q(
                        origin="model",
                        job__isnull=False,
                        block_version__isnull=False,
                        suggestion__isnull=True,
                        task__isnull=True,
                    )
                ),
                name="impact_item_origin",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        block_version__isnull=False, suggestion__isnull=True, task__isnull=True
                    )
                    | models.Q(
                        block_version__isnull=True, suggestion__isnull=False, task__isnull=True
                    )
                    | models.Q(
                        block_version__isnull=True, suggestion__isnull=True, task__isnull=False
                    )
                ),
                name="impact_item_target",
            ),
        ]


class ImpactDecision(models.Model):
    item = models.ForeignKey(ImpactItem, on_delete=models.CASCADE, related_name="decisions")
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=16)
    note = models.TextField()
    facts_snapshot = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "number"], name="unique_impact_decision_number"
            ),
            models.UniqueConstraint(
                fields=["item", "created_by", "request_key"], name="unique_impact_decision_request"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="impact_decision_number_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["pending", "handled", "retained", "unrelated"]),
                name="impact_decision_state",
            ),
            models.CheckConstraint(condition=~models.Q(note=""), name="impact_decision_note"),
        ]


class ExportTemplateVersion(models.Model):
    """由管理员登记的排版规则版本；不执行用户上传的宏或任意模板代码。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=80)
    number = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    layout = models.JSONField()
    rights_note = models.TextField()
    source_label = models.CharField(max_length=500)
    digest = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["code", "number"], name="unique_export_template_version"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="export_template_version_positive"
            ),
            models.CheckConstraint(
                condition=~models.Q(rights_note="") & ~models.Q(source_label=""),
                name="export_template_rights_source",
            ),
        ]


class ExportSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="exports")
    manuscript_revision = models.ForeignKey(ManuscriptRevision, on_delete=models.RESTRICT)
    disclosure_revision = models.ForeignKey(DisclosureRevision, on_delete=models.RESTRICT)
    template_version = models.ForeignKey(ExportTemplateVersion, on_delete=models.RESTRICT)
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="export_snapshot")
    content = models.JSONField()
    digest = models.CharField(max_length=64)
    renderer_version = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "request_key"],
                name="unique_export_snapshot_request",
            ),
        ]


class ExportSource(models.Model):
    """供撤回/删除查询的规范来源关系；导出内容仍来自不可变快照。"""

    snapshot = models.ForeignKey(ExportSnapshot, on_delete=models.CASCADE, related_name="sources")
    source_version = models.ForeignKey(MaterialVersion, on_delete=models.RESTRICT)
    state_version = models.PositiveIntegerField()
    usage_version = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "source_version"], name="unique_export_source"
            ),
            models.CheckConstraint(
                condition=models.Q(state_version__gt=0, usage_version__gt=0),
                name="export_source_versions_positive",
            ),
        ]


class ExportFile(models.Model):
    snapshot = models.ForeignKey(ExportSnapshot, on_delete=models.CASCADE, related_name="files")
    generation = models.PositiveIntegerField()
    bucket = models.CharField(max_length=100)
    object_key = models.CharField(max_length=200, unique=True)
    sha256 = models.CharField(max_length=64, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    published_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "generation"], name="unique_export_file_generation"
            ),
            models.CheckConstraint(
                condition=models.Q(generation__gt=0), name="export_file_generation_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(published_at__isnull=True)
                | (models.Q(size__gt=0) & ~models.Q(sha256="")),
                name="export_file_published_content",
            ),
        ]


class ExportDownload(models.Model):
    file = models.ForeignKey(ExportFile, on_delete=models.CASCADE, related_name="downloads")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class CleanupRequest(models.Model):
    """独立于项目生命周期的删除清单；不保存标题、原文或模型内容。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project_id = models.UUIDField()
    material_id = models.UUIDField(null=True)
    scope = models.CharField(max_length=16)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)
    manifest = models.JSONField()
    status = models.CharField(max_length=16, default="queued")
    generation = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_cleanup_request"
            ),
            models.CheckConstraint(
                condition=models.Q(scope="project", material_id__isnull=True)
                | models.Q(scope="material", material_id__isnull=False),
                name="cleanup_target_shape",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["queued", "running", "failed", "succeeded"]),
                name="cleanup_valid_status",
            ),
        ]
        indexes = [models.Index(fields=["status", "lease_until"])]


class CleanupItem(models.Model):
    request = models.ForeignKey(CleanupRequest, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=16)
    key = models.CharField(max_length=64)
    target = models.JSONField()
    status = models.CharField(max_length=16, default="pending")
    error_code = models.CharField(max_length=100, blank=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "key"], name="unique_cleanup_item"),
            models.CheckConstraint(
                condition=models.Q(kind__in=["database", "object", "graph"]),
                name="cleanup_item_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "failed", "removed", "shared"]),
                name="cleanup_item_status",
            ),
        ]


class CleanupAttempt(models.Model):
    request = models.ForeignKey(CleanupRequest, on_delete=models.CASCADE, related_name="attempts")
    generation = models.PositiveIntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=16, default="running")
    error_code = models.CharField(max_length=100, blank=True)
    errors = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["request", "generation"], name="unique_cleanup_attempt"
            ),
            models.CheckConstraint(
                condition=models.Q(generation__gt=0), name="cleanup_generation_positive"
            ),
        ]
