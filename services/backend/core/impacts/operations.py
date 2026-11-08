from core.models import ImpactItem, ImpactRun, MaterialChange


def changes(pid):
    return MaterialChange.objects.filter(source_version__material__project_id=pid).select_related(
        "source_version__material", "replacement__material"
    )


def runs(pid):
    return ImpactRun.objects.filter(
        change__source_version__material__project_id=pid
    ).select_related(
        "manuscript_revision", "change__source_version__material", "change__replacement__material"
    )


def items(pid):
    return (
        ImpactItem.objects.filter(run__change__source_version__material__project_id=pid)
        .select_related(
            "run__change__source_version__material",
            "run__change__replacement__material",
            "run__manuscript_revision",
            "block_version",
            "suggestion__decision",
            "task",
            "job",
        )
        .prefetch_related("decisions")
    )
