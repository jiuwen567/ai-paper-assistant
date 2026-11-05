"""Neo4j 只保存定位信息；路径内容与访问权限始终由 PostgreSQL 核验。"""

from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from neo4j import GraphDatabase

from core.evidence_links import link_changed, links
from core.feedback import location_data
from core.library import active_chunks, searchable_chunks
from core.models import (
    GraphEvent,
    GraphState,
    GraphTombstone,
    ManuscriptCitation,
    Project,
    ReviewFinding,
    RevisionBlock,
)

MAX_PATHS = 10000


class GraphUnavailable(Exception):
    pass


def driver():
    return GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        connection_timeout=3,
        connection_acquisition_timeout=3,
        max_transaction_retry_time=0,
    )


def mark_dirty(project_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT core_graph_dirty(%s::uuid)", [str(project_id)])
        return cursor.fetchone()[0]


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


def ensure_schema(session):
    session.run(
        "CREATE CONSTRAINT paper_project_key IF NOT EXISTS "
        "FOR (p:PaperProject) REQUIRE p.id IS UNIQUE"
    ).consume()
    session.run(
        "CREATE CONSTRAINT paper_node_key IF NOT EXISTS FOR (n:PaperNode) REQUIRE n.key IS UNIQUE"
    ).consume()


def apply_snapshot(snapshot):
    """项目锁与单一图事务替换投影；较旧或重复事件不能恢复旧边。"""
    with driver() as graph, graph.session() as session:
        ensure_schema(session)
        with session.begin_transaction(timeout=10) as tx:
            row = tx.run(
                "MERGE (p:PaperProject {id:$project}) "
                "ON CREATE SET p.revision=0, p.lock=0 "
                "SET p.lock=coalesce(p.lock,0)+1 "
                "RETURN p.revision AS revision, p.deleted AS deleted",
                project=snapshot["project"],
            ).single()
            if row["deleted"]:
                raise GraphUnavailable("project_deleted")
            if row["revision"] >= snapshot["revision"]:
                return row["revision"]
            tx.run(
                "MATCH (n:PaperNode {project:$project}) DETACH DELETE n",
                project=snapshot["project"],
            ).consume()
            tx.run(
                "UNWIND $nodes AS value CREATE (n:PaperNode) SET n=value, n.project=$project",
                nodes=snapshot["nodes"],
                project=snapshot["project"],
            ).consume()
            tx.run(
                "UNWIND $edges AS value "
                "MATCH (a:PaperNode {key:value.start}), (b:PaperNode {key:value.end}) "
                "CREATE (a)-[r:PAPER_EDGE]->(b) SET r.key=value.key, r.kind=value.kind",
                edges=snapshot["edges"],
            ).consume()
            tx.run(
                "MATCH (p:PaperProject {id:$project}) SET p.revision=$revision",
                project=snapshot["project"],
                revision=snapshot["revision"],
            ).consume()
            tx.commit()
            return snapshot["revision"]


def graph_paths(project_id, *, block_id=None, material_id=None, offset=0, limit=20):
    with driver() as graph, graph.session() as session, session.begin_transaction(timeout=5) as tx:
        row = tx.run(
            "MATCH (p:PaperProject {id:$project}) SET p.lock=coalesce(p.lock,0)+1 "
            "RETURN p.revision AS revision, p.deleted AS deleted",
            project=str(project_id),
        ).single()
        if row is None or row["deleted"]:
            return None, [], 0
        params = {
            "project": str(project_id),
            "block": str(block_id) if block_id else None,
            "material": str(material_id) if material_id else None,
        }
        match = (
            "MATCH (b:PaperNode {project:$project,kind:'block'})"
            "-[e:PAPER_EDGE {kind:'expresses'}]->"
            "(c:PaperNode {kind:'claim'})-[:PAPER_EDGE {kind:'uses'}]->"
            "(:PaperNode {kind:'evidence'})-[:PAPER_EDGE {kind:'from'}]->"
            "(m:PaperNode {kind:'material'}) "
            "WHERE ($block IS NULL OR b.block_id=$block) "
            "AND ($material IS NULL OR m.material_id=$material) "
        )
        count = tx.run(match + "RETURN count(DISTINCT c.path_id) AS count", **params).single()[
            "count"
        ]
        rows = tx.run(
            match + "RETURN DISTINCT c.path_id AS id ORDER BY id SKIP $offset LIMIT $limit",
            **params,
            offset=offset,
            limit=limit,
        )
        ids = [item["id"] for item in rows]
        return row["revision"], ids, count


def dispatch():
    from worker.tasks import sync_graph_events

    try:
        sync_graph_events.apply_async(retry=False)
    except Exception:
        # PostgreSQL outbox 未消费的记录由定时恢复，不把队列故障伪装成同步完成。
        pass


@transaction.atomic
def sync_project(project_id):
    project = Project.objects.select_for_update().filter(pk=project_id).first()
    if project is None:
        return False
    state = GraphState.objects.select_for_update().get(project=project)
    pending = GraphEvent.objects.filter(
        project=project, processed_at=None, revision__lte=state.revision
    )
    if not pending.exists():
        return True
    try:
        snapshot = project_snapshot(project.pk, state.revision)
        applied = apply_snapshot(snapshot)
        if applied != state.revision:
            raise GraphUnavailable("graph_revision_ahead")
    except Exception as error:
        # 不记录端点、凭据、原文或驱动异常正文。
        code = str(error) if isinstance(error, GraphUnavailable) else type(error).__name__
        state.last_error = code[:100]
        state.save(update_fields=["last_error", "updated_at"])
        from django.db.models import F

        pending.update(
            attempts=F("attempts") + 1,
            error_code=state.last_error,
            next_attempt_at=timezone.now() + timedelta(seconds=30),
        )
        return False
    state.applied_revision = state.revision
    state.last_error = ""
    state.save(update_fields=["applied_revision", "last_error", "updated_at"])
    pending.update(processed_at=timezone.now(), error_code="", next_attempt_at=None)
    return True


def recover_events():
    for tombstone in GraphTombstone.objects.filter(processed_at=None).order_by("created_at")[:10]:
        try:
            delete_projection(tombstone.project_id)
        except Exception as error:
            tombstone.error_code = type(error).__name__[:100]
            tombstone.save(update_fields=["error_code"])
        else:
            tombstone.processed_at = timezone.now()
            tombstone.error_code = ""
            tombstone.save(update_fields=["processed_at", "error_code"])
    projects = list(
        GraphEvent.objects.filter(processed_at=None)
        .filter(Q(next_attempt_at=None) | Q(next_attempt_at__lte=timezone.now()))
        .order_by("project_id")
        .values_list("project_id", flat=True)
        .distinct()[:10]
    )
    return {"projects": len(projects), "synchronized": sum(sync_project(pk) for pk in projects)}


def project_deleting(sender, instance, using, **kwargs):
    # Django 级联删除先发送所有 pre_delete，须在清理子记录前留下独立墓碑。
    Project.objects.using(using).select_for_update().get(pk=instance.pk)
    GraphTombstone.objects.using(using).get_or_create(project_id=instance.pk)


def delete_projection(project_id):
    with driver() as graph, graph.session() as session:
        ensure_schema(session)
        with session.begin_transaction(timeout=10) as tx:
            tx.run(
                "MERGE (p:PaperProject {id:$project}) "
                "SET p.lock=coalesce(p.lock,0)+1, p.deleted=true",
                project=str(project_id),
            ).consume()
            tx.run(
                "MATCH (n:PaperNode {project:$project}) DETACH DELETE n",
                project=str(project_id),
            ).consume()
            tx.commit()


def purge_projection(project_id):
    """只清理指定项目的投影；调用者必须先处理 PostgreSQL 访问与并发边界。"""
    with driver() as graph, graph.session() as session, session.begin_transaction(timeout=10) as tx:
        tx.run(
            "MATCH (p:PaperProject {id:$project}) SET p.lock=coalesce(p.lock,0)+1",
            project=str(project_id),
        ).consume()
        tx.run(
            "MATCH (n:PaperNode {project:$project}) DETACH DELETE n", project=str(project_id)
        ).consume()
        tx.run("MATCH (p:PaperProject {id:$project}) DELETE p", project=str(project_id)).consume()
        tx.commit()
