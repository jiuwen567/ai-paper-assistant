"""隔离环境恢复演练：只操作本脚本登记的随机自制项目，不调用生成模型。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["seed", "check", "delete", "replay-deletion", "check-deleted"]
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--deletion-ledger", type=Path, help="专用样例备份之后的删除记录")
    args = parser.parse_args()
    import environ

    environ.Env.read_env(args.env_file.resolve(), overwrite=True)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from rest_framework.test import APIClient

    from core.ai_jobs import sources_snapshot
    from core.cleanup import execute as execute_cleanup
    from core.export_templates import (
        DEFAULT_CODE,
        DEFAULT_LAYOUT,
        DEFAULT_NAME,
        DEFAULT_RIGHTS,
        DEFAULT_SOURCE,
        register_template,
    )
    from core.graph import mark_dirty, sync_project
    from core.library import default_bibliography
    from core.models import (
        CleanupRequest,
        ExportSnapshot,
        ManuscriptCitation,
        MaterialVersion,
        Project,
        ProjectPolicy,
    )
    from core.tests.test_cleanup import request_cleanup
    from core.tests.test_core_workflow import parsed
    from core.tests.test_disclosures import body as disclosure_body
    from core.tests.test_disclosures import save as save_disclosure
    from core.tests.test_exports import create as create_export
    from core.tests.test_exports import download
    from core.tests.test_graph import create as link_create
    from core.tests.test_graph import query
    from core.tests.test_manuscripts import payload, save
    from core.tests.test_materials import path
    from worker.tasks import execute_job

    if not settings.DEBUG:
        raise ValueError("恢复样例仅限 DEBUG 隔离环境。")
    client = APIClient(HTTP_HOST="localhost")

    def read_bytes(response):
        assert response.status_code == 200, response.status_code
        try:
            return b"".join(response.streaming_content)
        finally:
            response.close()

    if args.action == "seed":
        if args.state.exists():
            raise ValueError("状态文件已存在，禁止覆盖演练身份。")
        name = "deployment-eval-" + uuid4().hex
        user = get_user_model().objects.create_user(username=name)
        project = Project.objects.create(owner=user, name=name)
        ProjectPolicy.objects.create(project=project, version=1, created_by=user)
        client.force_authenticate(user)
        context = client, project, user
        texts = ["提高温度后反应速率增加。", "自制对照记录仅用于软件恢复演练。"]
        state = {"format": 1, "project": str(project.pk), "owner": name, "files": []}
        # 先保存身份；后续失败仍能定位此专用数据，不静默清掉诊断。
        args.state.parent.mkdir(parents=True, exist_ok=True)
        with args.state.open("x") as output:
            output.write(json.dumps(state, ensure_ascii=False, indent=2))
        args.state.chmod(0o600)
        with transaction.atomic():
            sources = [parsed(context, text, f"restore-{i}") for i, text in enumerate(texts)]
            manuscript = save(
                context,
                payload(
                    blocks=[
                        {"id": str(uuid4()), "heading_level": 0, "text": text} for text in texts
                    ]
                ),
            ).data
            for index, (version, run) in enumerate(sources):
                chunk = run.chunks.get()
                metadata = {
                    **default_bibliography(version),
                    "title": f"自制恢复材料{index}",
                    "authors": ["自制作者"],
                    "year": "2026",
                    "source_scope": "research",
                }
                assert (
                    client.put(
                        path(project, f"files/{version.pk}/bibliography/"),
                        {"version": 0, "snapshot": metadata},
                        format="json",
                    ).status_code
                    == 200
                )
                source = sources_snapshot(project.pk, [str(version.pk)])[0]
                ManuscriptCitation.objects.create(
                    block_version_id=manuscript["blocks"][index]["version_id"],
                    chunk=chunk,
                    snapshot={**source, "quote": chunk.text},
                    fingerprint=str(index) * 64,
                    created_by=user,
                )
                state["files"].append(
                    {
                        "id": str(version.pk),
                        "material": str(version.material_id),
                        "sha256": hashlib.sha256(texts[index].encode()).hexdigest(),
                    }
                )
            link_create(context, manuscript, sources[0], block_id=manuscript["blocks"][0]["id"])
            disclosure = save_disclosure(context, disclosure_body(context, verified=True))
            assert disclosure.status_code == 201
            template, _ = register_template(
                {
                    "code": DEFAULT_CODE,
                    "name": DEFAULT_NAME,
                    "layout": DEFAULT_LAYOUT,
                    "source_label": DEFAULT_SOURCE,
                    "rights_note": DEFAULT_RIGHTS,
                },
                user,
            )
            snapshot, _ = create_export(
                context,
                {
                    "manuscript_version": 1,
                    "disclosure_version": 1,
                    "template_version_id": str(template.pk),
                    "title": "自制恢复演练",
                    "author": "自制作者",
                    "captions": [],
                },
            )
            execute_job(str(snapshot.job_id))
            state.update(export=str(snapshot.pk), body=texts)
        # StreamingHttpResponse.close 会触发 request_finished；须在外层事务提交后下载。
        state["export_sha256"] = hashlib.sha256(read_bytes(download(context, snapshot))).hexdigest()
        args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        assert sync_project(project.pk)
        assert query(context)["count"] >= 2
        print("自制项目、两份原件、解析、引用、依据图与 Word 文件已登记。")
        return

    state = json.loads(args.state.read_text())
    project = Project.objects.select_related("owner").get(pk=state["project"])
    if (
        state.get("format") != 1
        or not state["owner"].startswith("deployment-eval-")
        or project.name != state["owner"]
        or project.owner.username != state["owner"]
    ):
        raise ValueError("只允许本脚本登记的专用自制项目。")
    client.force_authenticate(project.owner)
    context = client, project, project.owner
    for item in state["files"]:
        version = MaterialVersion.objects.filter(pk=item["id"]).first()
        if version and str(version.material.project_id) != state["project"]:
            raise ValueError("状态文件包含其他项目的材料。")
    if args.action in {"delete", "replay-deletion"}:
        if not args.deletion_ledger:
            raise ValueError("删除/重放须指定专用删除记录文件。")
        if args.action == "replay-deletion" or args.deletion_ledger.exists():
            ledger = json.loads(args.deletion_ledger.read_text())
            if (
                ledger.get("format") != 1
                or ledger.get("project") != state["project"]
                or ledger.get("material") != state["files"][0]["material"]
            ):
                raise ValueError("删除记录与专用恢复样例不匹配。")
        # 故意只重放专用样例第一份材料的删除；不是通用生产删除账本导入工具。
        version = MaterialVersion.objects.filter(pk=state["files"][0]["id"]).first()
        if version:
            with patch("core.cleanup.dispatch"):
                record, _ = request_cleanup(context, version.material, key="recovery-delete")
        else:
            record = CleanupRequest.objects.get(
                project_id=project.pk, created_by=project.owner, request_key="recovery-delete"
            )
        if record.status == "failed":
            with patch("core.cleanup_views.dispatch"):
                response = client.post(
                    f"/api/v1/cleanups/{record.pk}/",
                    {"generation": record.generation},
                    format="json",
                )
            assert response.status_code == 200
        execute_cleanup(record.pk)
        record.refresh_from_db()
        assert record.status == "succeeded", record.error_code
        if args.action == "delete" and not args.deletion_ledger.exists():
            ledger = {
                "format": 1,
                "project": state["project"],
                "material": state["files"][0]["material"],
                "request": str(record.pk),
                "created_at": record.created_at.isoformat(),
                "scope": "material",
            }
            with args.deletion_ledger.open("x") as output:
                output.write(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
            args.deletion_ledger.chmod(0o600)
        print("专用样例的删除已应用；请继续运行 check-deleted。")
        return
    # Neo4j 使用新数据卷；从 PostgreSQL 事实重新投影，不复制旧图数据库。
    with transaction.atomic():
        Project.objects.select_for_update().get(pk=project.pk)
        mark_dirty(project.pk)
    assert sync_project(project.pk)
    current = client.get(path(project, "manuscript/")).data
    if args.action == "check":
        assert [block["text"] for block in current["blocks"]] == state["body"]
        for item in state["files"]:
            raw = read_bytes(client.get(path(project, f"files/{item['id']}/")))
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        snapshot = ExportSnapshot.objects.get(pk=state["export"], project=project)
        assert (
            hashlib.sha256(read_bytes(download(context, snapshot))).hexdigest()
            == state["export_sha256"]
        )
        assert query(context)["status"] == "synced" and query(context)["count"] >= 2
        print("恢复核对通过：原件与 Word 摘要一致、正文与引用保留、图已重建。")
    else:
        assert client.get(path(project, f"files/{state['files'][0]['id']}/")).status_code == 404
        assert not ExportSnapshot.objects.filter(pk=state["export"]).exists()
        assert [block["text"] for block in current["blocks"]] == [state["body"][1]]
        survivor = state["files"][1]
        assert (
            hashlib.sha256(
                read_bytes(client.get(path(project, f"files/{survivor['id']}/")))
            ).hexdigest()
            == survivor["sha256"]
        )
        assert query(context)["status"] == "synced" and query(context)["count"] == 1
        print("删除重放核对通过：旧原件/派生正文/导出不可用，无关原件及正文保留。")


if __name__ == "__main__":
    main()
