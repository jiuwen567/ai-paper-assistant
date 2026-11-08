from django.db.models import F

from core.common.digests import digest
from core.common.errors import ParseFailure
from core.library.service import searchable_chunks
from core.models import BibliographyRevision

MAX_CHUNKS = 256


def sources_snapshot(project_id, version_ids, *, allow_empty=False):
    if allow_empty and not version_ids:
        return []
    chunks = list(
        searchable_chunks(project_id)
        .filter(run__source_version_id__in=version_ids)
        .select_related("run__source_version__material")
        .order_by("id")[: MAX_CHUNKS + 1]
    )
    if not chunks or len(chunks) > MAX_CHUNKS:
        raise ParseFailure("ai_source_limit", "请选择已有解析的资料，总片段数须为 1–256。")
    if {str(chunk.run.source_version_id) for chunk in chunks} != set(version_ids):
        raise ParseFailure("ai_source_unavailable", "所选资料不可用或尚未解析。")
    revisions = BibliographyRevision.objects.filter(
        bibliography__source_version_id__in=version_ids,
        number=F("bibliography__revision"),
    ).select_related("bibliography")
    metadata = {str(item.bibliography.source_version_id): item for item in revisions}
    result = []
    for chunk in chunks:
        source = chunk.run.source_version
        bibliography = metadata.get(str(source.pk))
        result.append(
            {
                "chunk_id": str(chunk.pk),
                "text_digest": digest(chunk.text),
                "parse_id": str(chunk.run_id),
                "source_version_id": str(source.pk),
                "sha256": source.sha256,
                "state_version": source.material.state_version,
                "bibliography_revision_id": str(bibliography.pk) if bibliography else None,
                "source_scope": bibliography.snapshot["source_scope"]
                if bibliography
                else "unknown",
            }
        )
    return result
