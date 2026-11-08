from core.graph.errors import GraphUnavailable
from core.graph.relations import link_changed, links
from core.library.service import active_chunks, searchable_chunks
from core.manuscripts.locations import location_data
from core.models import (
    ManuscriptCitation,
    ReviewFinding,
    RevisionBlock,
)

MAX_PATHS = 10000


def record(path_id, origin, revision, block, chunk, claim, quote, kind, state, **extra):
    location = location_data(revision, block)
    source = chunk.run.source_version
    return {
        "id": path_id,
        "origin": origin,
        "kind": kind,
        "state": state,
        "claim": claim,
        "evidence_quote": quote,
        "location": location,
        "block_version_id": str(block.pk),
        "block_id": str(block.block_id),
        "chunk_id": str(chunk.pk),
        "parse_id": str(chunk.run_id),
        "source_version_id": str(source.pk),
        "source_number": source.number,
        "material_id": str(source.material_id),
        "material_title": source.material.title,
        "anchor": chunk.anchor,
        **extra,
    }


def path_records(project_id, path_ids=None):
    """仅投影有可回查来源的路径。诊断确认只表示问题确认，不冒充支持关系确认。"""
    selected = set(path_ids) if path_ids is not None else None
    live = active_chunks(project_id).select_related("run__source_version__material")
    chunks = {str(chunk.pk): chunk for chunk in live}
    current_chunks = set(
        str(pk) for pk in searchable_chunks(project_id).values_list("pk", flat=True)
    )
    result = []
    author_links = links(project_id)
    findings = (
        ReviewFinding.objects.filter(
            review__job__project_id=project_id,
            review__job__status="succeeded",
        )
        .exclude(status="ignored")
        .select_related("review__manuscript_revision", "block_version")
    )
    citations = ManuscriptCitation.objects.filter(
        block_version__block__manuscript__project_id=project_id,
    ).select_related("block_version")
    if selected is not None:
        # IDs 来自受限图查询；只识别本项目数据库中存在的记录。
        author_links = author_links.filter(
            pk__in=[key.split(":")[1] for key in selected if key.startswith("author:")]
        )
        findings = findings.filter(
            pk__in=[key.split(":")[1] for key in selected if key.startswith("review:")]
        )
        citations = citations.filter(
            pk__in=[key.split(":")[1] for key in selected if key.startswith("citation:")]
        )
    for link in author_links:
        latest = max(link.decisions.all(), key=lambda item: item.number)
        chunk = chunks.get(str(link.chunk_id))
        if latest.state == "withdrawn" or chunk is None:
            continue
        result.append(
            record(
                f"author:{link.pk}",
                "author",
                link.manuscript_revision,
                link.block_version,
                chunk,
                link.claim,
                link.evidence_quote,
                latest.kind,
                "needs_review" if link_changed(link, latest) else "confirmed",
                link_id=str(link.pk),
                decision_version=latest.number,
                note=latest.note,
                bibliography_revision_id=str(link.bibliography_revision_id)
                if link.bibliography_revision_id
                else None,
            )
        )
    for finding in findings:
        for source in finding.model_output["citations"]:
            path_id = f"review:{finding.pk}:{source['chunk_id']}"
            chunk = chunks.get(source["chunk_id"])
            if chunk is None or (selected is not None and path_id not in selected):
                continue
            item = record(
                path_id,
                "model",
                finding.review.manuscript_revision,
                finding.block_version,
                chunk,
                finding.model_output["quote"],
                source["quote"],
                "diagnostic",
                "candidate",
                finding_id=str(finding.pk),
                finding_status=finding.status,
                model_support=finding.model_output["support"],
                bibliography_revision_id=source.get("bibliography_revision_id"),
            )
            item["needs_review"] = (
                item["location"]["stale"]
                or str(chunk.pk) not in current_chunks
                or source.get("state_version") != chunk.run.source_version.material.state_version
            )
            result.append(item)
    for citation in citations:
        chunk = chunks.get(str(citation.chunk_id))
        if chunk is None:
            continue
        initial = (
            RevisionBlock.objects.filter(block_version=citation.block_version)
            .select_related("revision")
            .order_by("revision__number")
            .first()
        )
        if initial is None:
            raise GraphUnavailable("citation_location_missing")
        item = record(
            f"citation:{citation.pk}",
            "citation",
            initial.revision,
            citation.block_version,
            chunk,
            citation.block_version.text,
            citation.snapshot["quote"],
            "cites",
            "citation",
            citation_id=str(citation.pk),
            bibliography_revision_id=(
                str(citation.bibliography_revision_id)
                if citation.bibliography_revision_id
                else None
            ),
        )
        item["needs_review"] = (
            item["location"]["stale"]
            or str(chunk.pk) not in current_chunks
            or citation.snapshot.get("state_version")
            != chunk.run.source_version.material.state_version
        )
        result.append(item)
    if len(result) > MAX_PATHS:
        raise GraphUnavailable("graph_capacity_exceeded")
    return result


def project_snapshot(project_id, revision):
    paths = path_records(project_id)
    nodes, edges = {}, {}
    for path in paths:
        ids = [
            ("block", path["block_version_id"]),
            ("claim", path["id"]),
            ("evidence", path["chunk_id"]),
            ("material", path["source_version_id"]),
        ]
        keys = []
        for kind, identity in ids:
            key = f"{project_id}:{kind}:{identity}"
            keys.append(key)
            nodes[key] = {"key": key, "kind": kind, "business_id": identity}
        nodes[keys[0]]["block_id"] = path["block_id"]
        nodes[keys[1]].update(
            path_id=path["id"], origin=path["origin"], state=path["state"], relation=path["kind"]
        )
        nodes[keys[3]]["material_id"] = path["material_id"]
        for start, end, kind in zip(keys, keys[1:], ["expresses", "uses", "from"], strict=False):
            key = f"{start}>{kind}>{end}"
            edges[key] = {"key": key, "start": start, "end": end, "kind": kind}
    return {
        "project": str(project_id),
        "revision": revision,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
    }
