from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from neo4j import GraphDatabase

from core.graph.errors import GraphUnavailable
from core.graph.snapshot import project_snapshot
from core.models import (
    GraphEvent,
    GraphState,
    GraphTombstone,
    Project,
)


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
