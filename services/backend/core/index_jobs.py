from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from core.embeddings import SEGMENT_SIZE, configuration, encode, sha256
from core.jobs import active, dispatch, finish, heartbeat, lock_job
from core.library import searchable_chunks
from core.models import ChunkEmbedding, EmbeddingIndex, Job
from core.parsing import ParseFailure

MAX_SEGMENTS = 5000


def corpus(project_id):
    chunks = (
        searchable_chunks(project_id)
        .select_related("run__source_version__material")
        .order_by("id")[:5001]
    )
    sources, segments = [], []
    for chunk in chunks:
        sources.append(
            {
                "id": str(chunk.pk),
                "sha256": sha256(chunk.text),
                "state_version": chunk.run.source_version.material.state_version,
            }
        )
        for start in range(0, len(chunk.text), SEGMENT_SIZE):
            if len(segments) >= MAX_SEGMENTS:
                raise ParseFailure("index_limit", "资料超过首版索引上限，请缩小项目范围。")
            text = chunk.text[start : start + SEGMENT_SIZE]
            segments.append(
                {
                    "chunk": chunk,
                    "start": start,
                    "end": start + len(text),
                    "text_sha256": sha256(text),
                    "text": text,
                }
            )
    return sources, segments


def create_index(project, user, key, policy_version):
    config = configuration()
    sources, segments = corpus(project.pk)
    if not segments:
        raise ParseFailure("index_empty", "暂无可索引的有效解析片段。")
    index_id = uuid4()
    job = Job.objects.create(
        project=project,
        created_by=user,
        kind="index",
        idempotency_key=key,
        ai_action="reading",
        policy_version=policy_version,
        input_snapshot={"index_id": str(index_id), "sources": sources, "embedding": config},
    )
    index = EmbeddingIndex.objects.create(
        id=index_id,
        job=job,
        **{
            key: config[key]
            for key in ["model_name", "dimension", "artifact_digest", "pipeline_version"]
        },
    )
    transaction.on_commit(lambda: dispatch(job.pk))
    return index


@transaction.atomic
def checkpoint(index, generation, sources, progress, *, final=False):
    job = lock_job(index.job_id)
    if not active(job, generation):
        return False
    if final:
        current, _ = corpus(job.project_id)
        unchanged = current == sources
    else:
        # 小批次只查有效身份和材料状态；全文摘要在发布事务中统一复核。
        current = (
            searchable_chunks(job.project_id)
            .filter(pk__in=[item["id"] for item in sources])
            .values_list("id", "run__source_version__material__state_version")
        )
        unchanged = {str(pk): state for pk, state in current} == {
            item["id"]: item["state_version"] for item in sources
        }
    if not unchanged or configuration() != job.input_snapshot["embedding"]:
        finish(job, Job.Status.CANCELLED, "index_input_changed", "资料或模型已变化，请重建索引。")
        return False
    return heartbeat(job.pk, generation, progress)


@transaction.atomic
def publish_index(index, generation, sources, segments):
    if not checkpoint(index, generation, sources, 95, final=True):
        return False
    job = lock_job(index.job_id)
    ChunkEmbedding.objects.bulk_create(
        [ChunkEmbedding(index=index, **segment) for segment in segments]
    )
    index.published_at = timezone.now()
    index.save()
    job.output = {"index_id": str(index.pk), "segments": len(segments)}
    job.progress = 100
    finish(job, Job.Status.SUCCEEDED)
    return True


def execute_index(job):
    index = EmbeddingIndex.objects.get(job=job)
    sources, segments = corpus(job.project_id)
    if sources != job.input_snapshot["sources"]:
        with transaction.atomic():
            current = lock_job(job.pk)
            if active(current, job.generation):
                finish(
                    current, Job.Status.CANCELLED, "index_input_changed", "资料已变化，请重建索引。"
                )
        return
    config = job.input_snapshot["embedding"]
    for start in range(0, len(segments), 8):
        if not checkpoint(index, job.generation, sources, 5 + int(85 * start / len(segments))):
            return
        batch = segments[start : start + 8]
        vectors = encode([item["text"] for item in batch], config)
        for item, vector in zip(batch, vectors, strict=True):
            item.pop("text")
            item["vector"] = vector
    publish_index(index, job.generation, sources, segments)
