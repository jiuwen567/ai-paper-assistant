"""删除仅使用随机测试桶和自制数据，不触及工作区里的实际资料。"""

from uuid import uuid4

import pytest
from django.db import transaction

from core.cleanup_plan import Plan
from core.models import ExportSnapshot, Job, Manuscript, Material, MaterialVersion, SourceChunk
from core.tests.test_exports import cited as export_cited
from core.tests.test_exports import create
from core.tests.test_exports import draft as export_draft
from core.tests.test_library import source as library_source
from core.tests.test_manuscripts import payload, save
from core.tests.test_materials import context as material_context
from core.tests.test_materials import intent

context = material_context
source = library_source
draft = export_draft
cited = export_cited

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_material_plan_covers_export_citations_and_preserves_unrelated_body(context, draft, cited):
    version, _ = cited
    snapshot, _ = create(context, draft[1])
    with transaction.atomic():
        plan = Plan(context[1], version.material)
        before = plan.preview()
        assert before["counts"]["materialversion"] == 1
        assert before["counts"]["exportsnapshot"] == 1
        assert len(before["removed_blocks"]) == 1
        assert before["removed_blocks"][0]["text"] == "  作者原稿\n保留空白。  "
        plan.delete_database(context[2], uuid4())
    assert not MaterialVersion.objects.exists()
    assert not SourceChunk.objects.exists()
    assert not ExportSnapshot.objects.exists()
    assert not Job.objects.exists()
    current = Manuscript.objects.get(project=context[1]).current_revision
    assert current.number == 2 and current.origin == "cleanup"
    assert list(
        current.items.order_by("position").values_list("block_version__text", flat=True)
    ) == ["第一章", "自制图题", "自制表题"]
    assert not snapshot.files.exists()


def test_material_plan_keeps_other_material_and_unreferenced_manuscript(context, source):
    material = source[0].material
    other = intent(context, request_key="other")
    assert save(context, payload()).status_code == 200
    with transaction.atomic():
        plan = Plan(context[1], material)
        assert not plan.preview()["removed_blocks"]
        plan.delete_database(context[2], uuid4())
    assert Material.objects.get().pk == other.material_id
    assert Manuscript.objects.get().current_revision.number == 1


def test_project_plan_keeps_no_business_rows_and_records_every_file(context, draft, cited):
    snapshot, _ = create(context, draft[1])
    with transaction.atomic():
        plan = Plan(context[1])
        assert plan.preview()["objects"] == 1
        assert plan.preview()["counts"]["exportsnapshot"] == 1
        plan.delete_database(context[2], uuid4())
    assert not Material.objects.exists()
    assert not Manuscript.objects.exists()
    assert not ExportSnapshot.objects.filter(pk=snapshot.pk).exists()


def request_cleanup(context, material=None, key=None):
    from unittest.mock import patch

    from core.models import CleanupRequest
    from core.tests.test_materials import path

    client, project, _ = context
    data = {
        "scope": "material" if material else "project",
        "material_id": str(material.pk) if material else None,
    }
    preview = client.post(path(project, "cleanup-preview/"), data, format="json")
    assert preview.status_code == 200, preview.data
    data.update(
        preview_token=preview.data["token"], confirmed=True, request_key=key or str(uuid4())
    )
    with patch("core.cleanup.dispatch"):
        response = client.post(path(project, "cleanup/"), data, format="json")
    assert response.status_code == 201, response.data
    return CleanupRequest.objects.get(pk=response.data["id"]), data


def test_cleanup_database_immediate_external_failure_retry_and_audit(context, source):
    from unittest.mock import patch

    from core.cleanup import execute
    from core.tests.test_materials import path

    version = source[0]
    record, data = request_cleanup(context, version.material)
    assert context[0].get(path(context[1], f"files/{version.pk}/")).status_code == 404
    assert record.status == "queued" and record.items.get(kind="database").status == "removed"
    assert not Job.objects.exists()
    with patch("core.cleanup.s3_client", side_effect=OSError("secret endpoint")):
        execute(record.pk)
    record.refresh_from_db()
    assert record.status == "failed" and record.items.get(kind="object").status == "failed"
    assert record.items.get(kind="graph").status == "removed"
    response = context[0].get(f"/api/v1/cleanups/{record.pk}/")
    assert response.status_code == 200 and "secret" not in str(response.data)
    assert "bucket" not in str(response.data) and "object_key" not in str(response.data)
    repeated = context[0].post(path(context[1], "cleanup/"), data, format="json")
    assert repeated.status_code == 200 and repeated.data["id"] == str(record.pk)
    with patch("core.cleanup_views.dispatch"):
        retry = context[0].post(f"/api/v1/cleanups/{record.pk}/", {"generation": 1}, format="json")
    assert retry.status_code == 200
    with patch("core.cleanup.remove_graph", side_effect=AssertionError("成功步骤不重复执行")):
        execute(record.pk)
    record.refresh_from_db()
    assert record.status == "succeeded" and record.generation == 2
    assert list(record.attempts.order_by("generation").values_list("status", flat=True)) == [
        "failed",
        "succeeded",
    ]
    assert record.attempts.get(generation=1).errors == [
        {"id": record.items.get(kind="object").pk, "kind": "object", "error_code": "OSError"}
    ]
    assert record.attempts.get(generation=2).errors == []


def test_project_cleanup_remains_queryable_after_project_removed_and_no_stale_worker(
    context, source
):
    from core.cleanup import execute
    from core.models import CleanupRequest, Project
    from core.tests.test_materials import path
    from worker.tasks import execute_job

    job_id = source[1].job_id
    record, data = request_cleanup(context)
    assert not Project.objects.filter(pk=context[1].pk).exists()
    execute_job(str(job_id))
    assert not Job.objects.exists()
    assert context[0].post(path(context[1], "cleanup/"), data, format="json").status_code == 200
    execute(record.pk)
    record.refresh_from_db()
    assert record.status == "succeeded"
    assert context[0].get(f"/api/v1/cleanups/{record.pk}/").status_code == 200
    assert CleanupRequest.objects.count() == 1


def test_expired_cleanup_lease_records_failure_and_old_generation_stops(context, source):
    from datetime import timedelta

    from django.utils import timezone

    from core.cleanup import claim, execute_item, recover_one
    from core.models import CleanupRequest

    record, _ = request_cleanup(context, source[0].material)
    claimed = claim(record.pk)
    CleanupRequest.objects.filter(pk=record.pk).update(
        lease_until=timezone.now() - timedelta(seconds=1)
    )
    recover_one(record.pk)
    record.refresh_from_db()
    assert record.status == "failed" and record.error_code == "lease_expired"
    assert record.attempts.get().finished_at
    assert not execute_item(record.pk, claimed.generation, record.items.get(kind="object").pk)


def test_shared_object_is_retained_until_last_registered_reference_removed(context, source, draft):
    from contextlib import closing

    from core.cleanup import execute
    from core.health import s3_client
    from core.models import ExportFile

    version = source[0]
    snapshot, _ = create(context, draft[1])
    ExportFile.objects.create(
        snapshot=snapshot, generation=1, bucket=version.bucket, object_key=version.object_key
    )
    record, _ = request_cleanup(context, version.material)
    execute(record.pk)
    record.refresh_from_db()
    assert record.status == "succeeded" and record.items.get(kind="object").status == "shared"
    with closing(s3_client()) as storage:
        assert (
            storage.head_object(Bucket=version.bucket, Key=version.object_key)["ContentLength"]
            == version.size
        )
    remaining, _ = request_cleanup(context)
    execute(remaining.pk)
    assert remaining.items.get(kind="object").status == "removed"


def test_imported_and_edited_copies_removed_without_deleting_author_original(context):
    from unittest.mock import patch

    from core.models import BlockVersion
    from core.tests.parse_samples import docx_sample
    from core.tests.test_materials import path, upload
    from core.tests.test_parse_jobs import create as parse
    from worker.tasks import execute_job

    client, project, _ = context
    original = payload()
    assert save(context, original).status_code == 200
    data = docx_sample()
    version = intent(context, data=data, name="self-authored.docx")
    with patch("core.parse_views.dispatch"):
        assert upload(context, version, data).status_code == 200
        run = parse(context, version)
        execute_job(str(run.job_id))
    preview = client.get(path(project, f"manuscript/imports/{run.pk}/")).data
    imported = client.post(
        path(project, "manuscript/imports/"),
        {
            "version": 1,
            "request_key": "import",
            "parse_id": str(run.pk),
            "token": preview["token"],
            "mode": "append",
        },
        format="json",
    )
    assert imported.status_code == 200
    changed = {key: imported.data[key] for key in ["research", "version"]}
    changed["request_key"] = "edit-import"
    changed["blocks"] = [
        {key: block[key] for key in ["id", "text", "heading_level"]}
        for block in imported.data["blocks"]
    ]
    changed["blocks"][-1]["text"] = "在导入位置上修订的派生正文"
    assert save(context, changed).status_code == 200
    record, _ = request_cleanup(context, version.material)
    assert record.manifest["targets"]["blockversion"]
    current = client.get(path(project, "manuscript/")).data
    assert current["version"] == 4 and current["origin"] == "cleanup"
    assert [b["text"] for b in current["blocks"]] == [b["text"] for b in original["blocks"]]
    assert not BlockVersion.objects.filter(text__contains="派生正文").exists()
    assert not BlockVersion.objects.filter(text="自制正文\t尾部").exists()
    assert client.get(path(project, "manuscript/history/2/")).status_code == 404
    assert client.get(path(project, "manuscript/history/1/")).status_code == 200


def test_stale_preview_and_reviewer_denied_and_request_history_private(context, source):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    from core.models import CleanupRequest, ProjectMember
    from core.tests.test_materials import path

    client, project, owner = context
    selection = {"scope": "material", "material_id": str(source[0].material_id)}
    before = client.post(path(project, "cleanup-preview/"), selection, format="json").data
    intent(
        context, request_key="new-version", material_id=str(source[0].material_id), base_revision=1
    )
    body = {
        **selection,
        "preview_token": before["token"],
        "request_key": "stale",
        "confirmed": True,
    }
    assert client.post(path(project, "cleanup/"), body, format="json").status_code == 409
    assert not CleanupRequest.objects.exists() and MaterialVersion.objects.count() == 2
    reviewer = get_user_model().objects.create_user(username="cleanup-reviewer")
    ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
    other = APIClient()
    other.force_authenticate(reviewer)
    assert (
        other.post(path(project, "cleanup-preview/"), selection, format="json").status_code == 403
    )
    record, _ = request_cleanup(context, source[0].material)
    assert other.get(f"/api/v1/cleanups/{record.pk}/").status_code == 404
    assert other.get("/api/v1/cleanups/").data["count"] == 0
    owner.is_active = False
    owner.save()
    assert client.get(f"/api/v1/cleanups/{record.pk}/").status_code == 403


def test_cleanup_manifest_and_completed_steps_cannot_be_changed(context, source):
    from django.db import IntegrityError
    from django.utils import timezone

    from core.models import CleanupItem, CleanupRequest

    record, _ = request_cleanup(context, source[0].material)
    for operation in [
        lambda: CleanupRequest.objects.filter(pk=record.pk).update(manifest={}),
        lambda: CleanupRequest.objects.filter(pk=record.pk).update(
            status="succeeded", completed_at=timezone.now()
        ),
        lambda: CleanupItem.objects.filter(request=record, kind="object").update(
            target={"bucket": "different"}
        ),
        lambda: CleanupItem.objects.filter(request=record, kind="database").update(
            status="pending"
        ),
    ]:
        with pytest.raises(IntegrityError), transaction.atomic():
            operation()


def test_late_upload_and_export_write_do_not_recreate_deleted_objects(context, source, draft):
    from unittest.mock import patch

    from rest_framework.exceptions import NotFound

    from core.export_jobs import prepare_file, store_export
    from core.jobs import claim
    from core.materials import store_file

    snapshot, _ = create(context, draft[1])
    job = claim(snapshot.job_id)
    artifact = prepare_file(snapshot, job.generation)
    version = source[0]
    request_cleanup(context)
    with patch("core.materials.s3_client") as upload_storage:
        with pytest.raises(NotFound):
            store_file(version, b"stale")
        upload_storage.assert_not_called()
    with patch("core.export_jobs.s3_client") as export_storage:
        with pytest.raises(Job.DoesNotExist):
            store_export(snapshot, job.generation, artifact, b"stale")
        export_storage.assert_not_called()


def test_project_cleanup_includes_objects_from_previous_failed_material_cleanup(context, source):
    from unittest.mock import patch

    from core.cleanup import execute

    previous, _ = request_cleanup(context, source[0].material)
    with patch("core.cleanup.s3_client", side_effect=OSError):
        execute(previous.pk)
    remaining, _ = request_cleanup(context)
    assert remaining.items.filter(kind="object").count() == 1
    execute(remaining.pk)
    remaining.refresh_from_db()
    assert remaining.status == "succeeded"


def test_old_graph_snapshot_cannot_recreate_deleted_material_path(context, draft, cited):
    from core.cleanup import execute
    from core.graph import apply_snapshot, project_snapshot, sync_project
    from core.models import GraphState

    project = context[1]
    assert sync_project(project.pk), GraphState.objects.get(project=project).last_error
    old = project_snapshot(project.pk, GraphState.objects.get(project=project).revision)
    assert old["nodes"]
    record, _ = request_cleanup(context, cited[0].material)
    execute(record.pk)
    record.refresh_from_db()
    assert record.status == "succeeded"
    state = GraphState.objects.get(project=project)
    assert state.applied_revision == state.revision > old["revision"]
    assert apply_snapshot(old) == state.revision
    assert not project_snapshot(project.pk, state.revision)["nodes"]


def test_concurrent_identical_project_delete_returns_one_manifest(context, source):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from unittest.mock import patch

    from django.db import close_old_connections
    from rest_framework.test import APIClient

    from core.models import CleanupRequest
    from core.tests.test_materials import path

    client, project, user = context
    selection = {"scope": "project", "material_id": None}
    preview = client.post(path(project, "cleanup-preview/"), selection, format="json").data
    body = {
        **selection,
        "preview_token": preview["token"],
        "confirmed": True,
        "request_key": "parallel",
    }
    barrier = Barrier(2)

    def remove():
        close_old_connections()
        try:
            api = APIClient()
            api.force_authenticate(user)
            barrier.wait(timeout=10)
            response = api.post(path(project, "cleanup/"), body, format="json")
            return response.status_code, response.data
        finally:
            close_old_connections()

    with patch("core.cleanup.dispatch"), ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: remove(), range(2)))
    assert sorted(status for status, _ in results) == [200, 201], results
    assert CleanupRequest.objects.count() == 1
    assert results[0][1]["id"] == results[1][1]["id"]


def test_upload_in_progress_finishes_before_cleanup_manifest_and_objects_removed(context):
    import hashlib
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    from threading import Event
    from unittest.mock import patch

    from django.db import close_old_connections

    from core.access import require_project
    from core.cleanup import create_cleanup, execute
    from core.health import s3_client
    from core.materials import claim_upload, read_and_verify, store_file
    from core.models import CleanupRequest

    data = b"self-authored concurrent upload"
    version = intent(context, data=data)
    submitted = claim_upload(context[2], version.pk, hashlib.sha256(data).hexdigest())
    written, release, deleting = Event(), Event(), Event()

    def wait_after_write(storage, item):
        read_and_verify(storage, item)
        written.set()
        assert release.wait(10)

    def upload():
        close_old_connections()
        try:
            store_file(submitted, data)
        finally:
            close_old_connections()

    def remove():
        close_old_connections()
        try:
            with transaction.atomic():
                deleting.set()
                project = require_project(context[2], context[1].pk, write=True, lock=True)
                record = create_cleanup(
                    Plan(project, version.material), context[2], "inflight", "a" * 64
                )
                return record.pk
        finally:
            close_old_connections()

    with (
        patch("core.materials.read_and_verify", side_effect=wait_after_write),
        patch("core.cleanup.dispatch"),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        upload_future = pool.submit(upload)
        assert written.wait(10)
        delete_future = pool.submit(remove)
        assert deleting.wait(10) and not delete_future.done()
        release.set()
        upload_future.result(timeout=15)
        record_id = delete_future.result(timeout=15)
    execute(record_id)
    assert CleanupRequest.objects.get(pk=record_id).status == "succeeded"
    with closing(s3_client()) as storage:
        assert not storage.list_objects_v2(Bucket=version.bucket).get("Contents")


def test_coauthor_cannot_delete_project_and_database_failure_rolls_back(context, source):
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    from core.models import CleanupRequest, ProjectMember
    from core.tests.test_materials import path

    client, project, _ = context
    author = get_user_model().objects.create_user(username="cleanup-coauthor")
    ProjectMember.objects.create(project=project, user=author, role="author")
    other = APIClient()
    other.force_authenticate(author)
    assert (
        other.post(
            path(project, "cleanup-preview/"),
            {"scope": "project", "material_id": None},
            format="json",
        ).status_code
        == 403
    )
    selection = {"scope": "material", "material_id": str(source[0].material_id)}
    preview = other.post(path(project, "cleanup-preview/"), selection, format="json")
    assert preview.status_code == 200
    with patch(
        "core.cleanup_plan.Plan.delete_database",
        side_effect=RuntimeError("simulated database failure"),
    ):
        with pytest.raises(RuntimeError):
            client.post(
                path(project, "cleanup/"),
                {
                    **selection,
                    "preview_token": preview.data["token"],
                    "request_key": "rollback",
                    "confirmed": True,
                },
                format="json",
            )
    assert not CleanupRequest.objects.exists()
    assert MaterialVersion.objects.filter(pk=source[0].pk).exists()


@pytest.mark.parametrize("running", [False, True])
def test_deleted_source_stops_pending_ai_search_parse_and_new_export(
    context, draft, cited, running
):
    from core.jobs import claim
    from core.models import AIEvent
    from core.tests.test_ai_jobs import provider
    from core.tests.test_materials import path
    from core.tests.test_reading import create_reading
    from worker.tasks import execute_job

    client, project, _ = context
    version, _ = cited
    chunk = SourceChunk.objects.get(run__source_version=version)
    snapshot, export_data = create(context, draft[1])
    assert client.get(path(project, "search/?q=" + chunk.text[:2])).data["results"]
    with provider(lambda *_: []) as calls:
        job = create_reading(context, [cited])
        if running:
            assert claim(job.pk).status == "running"
        record, _ = request_cleanup(context, version.material)
        assert str(job.pk) in record.manifest["targets"]["job"]
        assert not Job.objects.filter(pk=job.pk).exists()
        assert not AIEvent.objects.filter(job_id=job.pk).exists()
        execute_job(str(job.pk))
        response = client.post(
            path(project, "reading/tasks/"),
            {
                "idempotency_key": "after-delete",
                "policy_version": 1,
                "purpose": "reading",
                "version_ids": [str(version.pk)],
            },
            format="json",
        )
        assert response.status_code == 400 and response.data["code"] == "ai_source_limit"
        assert not calls
    assert client.get(path(project, "search/?q=" + chunk.text[:2])).data["results"] == []
    assert (
        client.post(
            path(project, f"files/{version.pk}/parses/"),
            {
                "idempotency_key": "after-delete",
            },
            format="json",
        ).status_code
        == 404
    )
    assert client.get(path(project, f"exports/{snapshot.pk}/download/")).status_code == 404
    assert client.post(path(project, "exports/"), export_data, format="json").status_code == 409


@pytest.mark.parametrize("kind", ["upload", "job"])
def test_project_deleted_between_worker_lookup_and_lock_stops_cleanly(context, source, kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from unittest.mock import patch

    from django.db import close_old_connections
    from rest_framework.exceptions import NotFound

    from core.materials import store_file
    from core.models import Project
    from worker.tasks import execute_job

    reached, deleted = Event(), Event()
    main_thread = current_thread()
    select = Project.objects.select_for_update

    def locked_query(*args, **kwargs):
        query = select(*args, **kwargs)
        if current_thread() is not main_thread:
            get = query.get

            def wait_before_lock(*args, **kwargs):
                reached.set()
                assert deleted.wait(10)
                return get(*args, **kwargs)

            query.get = wait_before_lock
        return query

    def late_worker():
        close_old_connections()
        try:
            if kind == "upload":
                with pytest.raises(NotFound):
                    store_file(source[0], b"stale")
            else:
                execute_job(str(source[1].job_id))
        finally:
            close_old_connections()

    with patch.object(Project.objects, "select_for_update", side_effect=locked_query):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(late_worker)
            try:
                assert reached.wait(10)
                request_cleanup(context)
            finally:
                deleted.set()
            future.result(timeout=15)
    assert not Project.objects.filter(pk=context[1].pk).exists()


@pytest.mark.parametrize("legacy", [False, True])
def test_mixed_import_history_keeps_other_source_and_its_future_cleanup(context, draft, legacy):
    import importlib
    import io
    from unittest.mock import patch

    from django.db import connection
    from docx import Document

    from core.models import ContentBlock
    from core.tests.test_disclosures import body as disclosure_body
    from core.tests.test_disclosures import save as save_disclosure
    from core.tests.test_materials import path, upload
    from core.tests.test_parse_jobs import create as parse
    from worker.tasks import execute_job

    client, project, _ = context
    sources = []
    create_block = ContentBlock.objects.create

    def old_create(**kwargs):
        if legacy:
            kwargs.pop("imported_from_id", None)
        return create_block(**kwargs)

    for number, label in enumerate(["甲", "乙"], 1):
        document = Document()
        document.add_paragraph(f"自制导入材料{label}，只属于这一份资料。")
        output = io.BytesIO()
        document.save(output)
        content = output.getvalue()
        version = intent(context, data=content, name=f"sample-{number}.docx", request_key=label)
        with patch("core.parse_views.dispatch"):
            assert upload(context, version, content).status_code == 200
            run = parse(context, version, key=label)
            execute_job(str(run.job_id))
        preview = client.get(path(project, f"manuscript/imports/{run.pk}/")).data
        with patch.object(ContentBlock.objects, "create", side_effect=old_create):
            response = client.post(
                path(project, "manuscript/imports/"),
                {
                    "version": number,
                    "request_key": label,
                    "parse_id": str(run.pk),
                    "token": preview["token"],
                    "mode": "append",
                },
                format="json",
            )
        assert response.status_code == 200, response.data
        sources.append(version)
    if legacy:
        migration = importlib.import_module("core.migrations.0035_block_import_origin")
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(migration.BACKFILL)
    assert ContentBlock.objects.filter(imported_from__in=sources).count() == 2
    request_cleanup(context, sources[0].material)
    current = client.get(path(project, "manuscript/")).data
    assert current["version"] == 4
    assert [b["text"] for b in current["blocks"]][-1] == "自制导入材料乙，只属于这一份资料。"
    assert len(current["blocks"]) == len(draft[0]["blocks"]) + 1
    # 原导入历史已被清理，当前块仍保留固定来源，供新导出和下一次删除使用。
    assert client.get(path(project, "manuscript/history/3/")).status_code == 404
    saved = save_disclosure(context, disclosure_body(context, verified=True))
    assert saved.status_code == 201
    snapshot, _ = create(
        context,
        {
            **draft[1],
            "manuscript_version": 4,
            "disclosure_version": saved.data["saved_number"],
        },
    )
    assert list(snapshot.sources.values_list("source_version_id", flat=True)) == [sources[1].pk]
    request_cleanup(context, sources[1].material)
    current = client.get(path(project, "manuscript/")).data
    assert current["version"] == 5
    assert [b["text"] for b in current["blocks"]] == [b["text"] for b in draft[0]["blocks"]]
    assert (
        not snapshot.files.exists() and not ExportSnapshot.objects.filter(pk=snapshot.pk).exists()
    )


def test_imported_block_origin_is_same_project_and_immutable(context, source):
    from django.db import IntegrityError

    from core.models import ContentBlock, Project

    other = Project.objects.create(owner=context[2], name="自制隔离项目")
    other_manuscript = Manuscript.objects.create(project=other)
    with pytest.raises(IntegrityError), transaction.atomic():
        ContentBlock.objects.create(manuscript=other_manuscript, imported_from=source[0])
    manuscript = Manuscript.objects.create(project=context[1])
    block = ContentBlock.objects.create(manuscript=manuscript, imported_from=source[0])
    with pytest.raises(IntegrityError), transaction.atomic():
        ContentBlock.objects.filter(pk=block.pk).update(imported_from=None)
