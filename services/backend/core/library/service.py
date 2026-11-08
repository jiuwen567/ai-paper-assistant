from django.db.models import OuterRef, Subquery

from core.materials.queries import published_chunks
from core.models import Bibliography, BibliographyRevision, ParseRun


def active_chunks(project_id):
    return (
        published_chunks(project_id)
        .filter(
            run__source_version__material__access_state="active",
        )
        .exclude(run__source_version__usage_state="withdrawn")
    )


def searchable_chunks(project_id):
    # 同一原件重新解析后只检索最近成功版本，历史证据继续引用原片段。
    latest = (
        ParseRun.objects.filter(
            source_version_id=OuterRef("run__source_version_id"),
            published_at__isnull=False,
            job__status="succeeded",
        )
        .order_by("-number")
        .values("id")[:1]
    )
    return active_chunks(project_id).filter(
        run_id=Subquery(latest), run__source_version__usage_state="active"
    )


def default_bibliography(source):
    return {
        "title": source.material.title,
        "authors": [],
        "year": "",
        "doi": "",
        "url": "",
        "source_scope": "unknown",
        "abstract": "",
        "note": "",
        "tags": [],
    }


def current_bibliography(source, user):
    # 调用者持有项目锁，确保初始题录和修订序号唯一。
    record, _ = Bibliography.objects.get_or_create(source_version=source)
    if record.revision == 0:
        record.revision = 1
        record.save()
        BibliographyRevision.objects.create(
            bibliography=record, number=1, snapshot=default_bibliography(source), created_by=user
        )
    return record, record.revisions.get(number=record.revision)
