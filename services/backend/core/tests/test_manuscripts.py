import copy
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from rest_framework.test import APIClient

from core.models import (
    BlockVersion,
    ContentBlock,
    Manuscript,
    ManuscriptRevision,
    Material,
    Project,
    ProjectMember,
    RevisionBlock,
)
from core.tests.parse_samples import docx_sample
from core.tests.test_materials import context as material_context
from core.tests.test_materials import intent, path, upload
from core.tests.test_parse_jobs import create
from worker.tasks import execute_job

context = material_context
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def payload(version=0, **changes):
    return {
        "version": version,
        "request_key": str(uuid4()),
        "research": {"question": "作者提出的问题", "method": "作者的方法", "result": "作者的结果"},
        "blocks": [
            {"id": str(uuid4()), "heading_level": 1, "text": "第一章"},
            {"id": str(uuid4()), "heading_level": 0, "text": "  作者原稿\n保留空白。  "},
        ],
        **changes,
    }


def save(context, body):
    client, project, _ = context
    return client.put(path(project, "manuscript/"), body, format="json")


def test_edit_history_restore_stable_blocks_and_idempotent_requests(context):
    client, project, _ = context
    url = path(project, "manuscript/")
    assert client.get(url).data["version"] == 0
    body = payload()
    first = save(context, body)
    assert first.status_code == 200, first.data
    assert first.data["blocks"][1]["text"] == body["blocks"][1]["text"]
    assert save(context, body).data["version"] == 1
    assert (
        save(context, {**body, "research": {**body["research"], "result": "不同"}}).status_code
        == 409
    )
    changed = copy.deepcopy(body)
    changed.update(version=1, request_key="second")
    changed["blocks"][1]["text"] = "作者修订正文"
    changed["research"]["result"] = "作者修订结果"
    second = save(context, changed)
    assert second.status_code == 200, second.data
    assert second.data["blocks"][0]["version_id"] == first.data["blocks"][0]["version_id"]
    assert second.data["blocks"][1]["id"] == first.data["blocks"][1]["id"]
    assert second.data["blocks"][1]["number"] == 2
    assert save(context, {**changed, "request_key": "stale"}).status_code == 409
    assert save(context, body).data["current_version"] == 2
    assert client.get(url + "history/").data["count"] == 2
    assert client.get(url + "history/1/").data["blocks"] == first.data["blocks"]
    diff = client.get(url + "diff/?before=1&after=2").data
    assert diff["research"]["result"]["after"] == "作者修订结果"
    assert diff["blocks"][0]["kinds"] == ["modified"]
    restore = {"version": 2, "from_version": 1, "request_key": "restore"}
    restored = client.post(url + "restore/", restore, format="json")
    assert restored.status_code == 200, restored.data
    assert restored.data["version"] == 3 and restored.data["blocks"] == first.data["blocks"]
    assert restored.data["research"] == first.data["research"]
    assert client.post(url + "restore/", restore, format="json").data["version"] == 3
    assert BlockVersion.objects.count() == 3
    assert client.get(url + "history/").data["count"] == 3
    assert client.get(url + "diff/?before=1&after=3").data["blocks"] == []


def test_two_clients_have_one_winner(context):
    _, project, user = context
    barrier = Barrier(2)
    body = payload()

    def update(key):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=user.pk))
            barrier.wait(timeout=10)
            return client.put(
                path(project, "manuscript/"), {**body, "request_key": key}, format="json"
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(update, ["window-one", "window-two"]))
    assert sorted(statuses) == [200, 409]
    assert ManuscriptRevision.objects.count() == 1


def test_permissions_and_foreign_block_identity(context):
    client, project, owner = context
    saved = save(context, payload()).data
    other = Project.objects.create(owner=owner, name="另一个项目")
    wrong = payload(
        blocks=[{key: saved["blocks"][0][key] for key in ["id", "text", "heading_level"]}]
    )
    assert client.put(path(other, "manuscript/"), wrong, format="json").status_code == 400
    assert not Manuscript.objects.filter(project=other).exists()
    reviewer = get_user_model().objects.create_user(username="manuscript-reviewer")
    ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
    client.force_authenticate(reviewer)
    assert client.get(path(project, "manuscript/")).status_code == 200
    assert save(context, payload(1)).status_code == 403
    assert (
        client.post(
            path(project, "manuscript/restore/"),
            {"version": 1, "from_version": 0, "request_key": "no"},
            format="json",
        ).status_code
        == 403
    )
    ProjectMember.objects.filter(user=reviewer).delete()
    for suffix in ["", "history/", "history/1/", "diff/?before=0&after=1", "imports/"]:
        assert client.get(path(project, "manuscript/" + suffix)).status_code == 404


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "foreign_version", "title", "level", "many", "long", "extra", "research"],
)
def test_rejects_bad_content_atomically(context, mutation):
    body = payload()
    if mutation == "duplicate":
        body["blocks"].append(body["blocks"][0])
    elif mutation == "foreign_version":
        body["blocks"][0]["version_id"] = str(uuid4())
    elif mutation == "title":
        body["blocks"][0]["text"] = " "
    elif mutation == "level":
        body["blocks"][0]["heading_level"] = 10
    elif mutation == "many":
        body["blocks"] = [{"id": str(uuid4()), "text": "a", "heading_level": 0} for _ in range(501)]
    elif mutation == "long":
        body["blocks"][1]["text"] = "x" * 20001
    elif mutation == "extra":
        body["confirmed_by_model"] = True
    else:
        body["research"]["ai_generated"] = True
    assert save(context, body).status_code == 400
    assert not ManuscriptRevision.objects.exists() and not BlockVersion.objects.exists()


def test_reorder_remove_and_add_diff(context):
    client, project, _ = context
    body = payload()
    assert save(context, body).status_code == 200
    new = payload(
        1, blocks=[body["blocks"][1], {"id": str(uuid4()), "heading_level": 2, "text": "新章节"}]
    )
    assert save(context, new).status_code == 200
    changes = client.get(path(project, "manuscript/diff/?before=1&after=2")).data["blocks"]
    assert [item["kinds"] for item in changes] == [["removed"], ["moved"], ["added"]]


def test_database_rejects_foreign_relations_and_history_updates(context):
    client, project, user = context
    save(context, payload())
    first = Manuscript.objects.get(project=project)
    other_project = Project.objects.create(owner=user, name="数据库约束测试")
    client.put(path(other_project, "manuscript/"), payload(), format="json")
    second = Manuscript.objects.get(project=other_project)
    item = first.current_revision.items.first()
    for operation in [
        lambda: Manuscript.objects.filter(pk=first.pk).update(
            current_revision=second.current_revision
        ),
        lambda: RevisionBlock.objects.create(
            revision=second.current_revision,
            block=item.block,
            block_version=item.block_version,
            position=2,
        ),
        lambda: RevisionBlock.objects.create(
            revision=first.current_revision,
            block=first.blocks.exclude(pk=item.block_id).first(),
            block_version=item.block_version,
            position=2,
        ),
        lambda: BlockVersion.objects.filter(pk=item.block_version_id).update(text="篡改历史"),
        lambda: ManuscriptRevision.objects.filter(pk=first.current_revision_id).update(research={}),
        lambda: RevisionBlock.objects.filter(pk=item.pk).update(position=5),
        lambda: ContentBlock.objects.filter(pk=item.block_id).update(manuscript=second),
    ]:
        with pytest.raises(IntegrityError), transaction.atomic():
            operation()
    project.delete()
    assert Manuscript.objects.count() == 1


@pytest.fixture
def parsed_docx(context):
    # 超过解析分片长度的顶层段落，导入须重组而非拆成多个正文块。
    source = io.BytesIO(docx_sample())
    output = io.BytesIO()
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(output, "w") as new:
        for name in old.namelist():
            data = old.read(name)
            if name == "word/document.xml":
                data = data.replace("自制正文".encode(), ("作者段落" * 1100).encode())
            new.writestr(name, data)
    data = output.getvalue()
    version = intent(context, data=data, name="original.docx")
    assert upload(context, version, data).status_code == 200
    with patch("core.materials.parse_views.dispatch"):
        run = create(context, version)
    execute_job(str(run.job_id))
    return version, run


def test_docx_import_preview_append_replace_and_stale_sources(context, parsed_docx):
    client, project, _ = context
    source, run = parsed_docx
    base = path(project, "manuscript/")
    assert client.get(base + "imports/").data["count"] == 1
    preview = client.get(base + f"imports/{run.pk}/").data
    assert len(preview["blocks"]) == 2
    assert preview["blocks"][0]["heading_level"] == 1
    assert preview["blocks"][1]["text"] == "作者段落" * 1100 + "\t尾部"
    assert preview["source"]["coverage"] == "partial" and preview["source"]["warnings"]
    body = payload()
    save(context, body)
    request = {
        "version": 1,
        "request_key": "import",
        "parse_id": str(run.pk),
        "token": preview["token"],
        "mode": "append",
    }
    response = client.post(base + "imports/", request, format="json")
    assert response.status_code == 200, response.data
    assert len(response.data["blocks"]) == 4 and response.data["research"] == body["research"]
    assert client.post(base + "imports/", request, format="json").data["version"] == 2
    replaced = client.post(
        base + "imports/",
        {**request, "version": 2, "request_key": "replace", "mode": "replace"},
        format="json",
    )
    assert replaced.status_code == 200 and len(replaced.data["blocks"]) == 2
    assert replaced.data["research"] == body["research"]
    Material.objects.filter(pk=source.material_id).update(state_version=2)
    failed = client.post(
        base + "imports/", {**request, "version": 3, "request_key": "stale-source"}, format="json"
    )
    assert failed.status_code == 409
    assert client.get(base).data["version"] == 3
    Material.objects.filter(pk=source.material_id).update(access_state="withdrawn")
    assert client.get(base + f"imports/{run.pk}/").status_code == 409
    assert client.get(base + "imports/").data["count"] == 0


def test_empty_restore_and_invalid_history_arguments(context):
    client, project, _ = context
    save(context, payload())
    base = path(project, "manuscript/")
    response = client.post(
        base + "restore/",
        {
            "version": 1,
            "from_version": 0,
            "request_key": "empty",
        },
        format="json",
    )
    assert response.status_code == 200 and response.data["version"] == 2
    assert response.data["blocks"] == []
    assert client.get(base + "history/1/").data["blocks"]
    for suffix in [
        "diff/?before=x&after=1",
        "diff/?before=-1&after=0",
        "diff/?before=999999999999999999&after=1",
        "history/999999999999999999/",
    ]:
        assert client.get(base + suffix).status_code == 400


def test_import_rejects_old_parse_cross_project_and_modified_preview(context, parsed_docx):
    client, project, user = context
    source, run = parsed_docx
    base = path(project, "manuscript/")
    preview = client.get(base + f"imports/{run.pk}/").data
    body = {
        "version": 0,
        "request_key": "import",
        "parse_id": str(run.pk),
        "token": "0" * 64,
        "mode": "replace",
    }
    assert client.post(base + "imports/", body, format="json").status_code == 409
    other = Project.objects.create(owner=user, name="另一份原稿")
    assert client.get(path(other, f"manuscript/imports/{run.pk}/")).status_code == 404
    with patch("core.materials.parse_views.dispatch"):
        replacement = create(context, source, key="reparse")
    execute_job(str(replacement.job_id))
    assert client.get(base + f"imports/{run.pk}/").status_code == 409
    assert (
        client.post(
            base + "imports/", {**body, "token": preview["token"]}, format="json"
        ).status_code
        == 409
    )
    assert not ManuscriptRevision.objects.exists()
