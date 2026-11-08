from core.models import Job, SourceChunk


def published_chunks(project_id):
    return SourceChunk.objects.filter(
        run__source_version__material__project_id=project_id,
        run__source_version__status="available",
        run__published_at__isnull=False,
        run__job__status=Job.Status.SUCCEEDED,
    )
