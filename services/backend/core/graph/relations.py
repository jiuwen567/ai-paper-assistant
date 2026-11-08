from rest_framework.exceptions import ValidationError

from core.library.service import searchable_chunks
from core.manuscripts.locations import location_data
from core.models import EvidenceLink


def locate(text, quote, occurrence):
    offset = -1
    for _ in range(occurrence):
        offset = text.find(quote, offset + 1)
        if offset < 0:
            raise ValidationError("引文或出现次序与原文不符，请重新核对。")
    return offset


def links(project_id):
    return (
        EvidenceLink.objects.filter(project_id=project_id)
        .select_related(
            "manuscript_revision", "block_version", "chunk__run__source_version__material"
        )
        .prefetch_related("decisions")
    )


def link_changed(link, decision):
    location = location_data(link.manuscript_revision, link.block_version)
    source = link.chunk.run.source_version
    return (
        location["stale"]
        or source.material.state_version != decision.source_state_version
        or not searchable_chunks(link.project_id).filter(pk=link.chunk_id).exists()
    )
