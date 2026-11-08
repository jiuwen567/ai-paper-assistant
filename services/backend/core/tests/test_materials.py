"""自制文件，独立 PostgreSQL 测试库和随机 SeaweedFS 测试桶。"""

import hashlib
import io
from contextlib import closing
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from pypdf import PdfWriter
from rest_framework.test import APIClient

from core.materials.files import validate_file
from core.materials.service import claim_upload, reconcile_upload
from core.models import MaterialVersion, Project, ProjectMember, ProjectPolicy
from core.storage.s3 import s3_client

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def context():
    user = get_user_model().objects.create_user(username="upload-author")
    client = APIClient()
    client.force_authenticate(user)
    project = Project.objects.create(owner=user, name="自制材料测试")
    ProjectPolicy.objects.create(project=project, version=1, created_by=user)
    bucket = f"paper-test-{uuid4().hex}"
    with override_settings(MATERIAL_BUCKET=bucket):
        with closing(s3_client()) as storage:
            storage.create_bucket(Bucket=bucket)
        try:
            yield client, project, user
        finally:
            with closing(s3_client()) as storage:
                for item in storage.list_objects_v2(Bucket=bucket).get("Contents", []):
                    storage.delete_object(Bucket=bucket, Key=item["Key"])
                storage.delete_bucket(Bucket=bucket)


def path(project, suffix):
    return f"/api/v1/projects/{project.pk}/{suffix}"


def intent(context, data=b"self-authored text", name="sample.txt", **changes):
    client, project, _ = context
    response = client.post(
        path(project, "uploads/"),
        {
            "title": "自制材料",
            "request_key": "upload-1",
            "file_name": name,
            "size": len(data),
            **changes,
        },
        format="json",
    )
    assert response.status_code in [200, 201], response.data
    return MaterialVersion.objects.get(pk=response.data["id"])


def upload(context, version, data=b"self-authored text"):
    client, project, _ = context
    return client.post(
        path(project, f"uploads/{version.pk}/"),
        {
            "file": SimpleUploadedFile(version.file_name, data),
        },
        format="multipart",
    )


def test_real_s3_roundtrip_hash_idempotency_and_versions(context):
    client, project, _ = context
    version = intent(context)
    assert intent(context).pk == version.pk
    for _ in range(2):
        response = upload(context, version)
        assert response.status_code == 200, response.data
        assert response.data["status"] == "available"
    version.refresh_from_db()
    assert version.sha256 == hashlib.sha256(b"self-authored text").hexdigest()
    second = intent(
        context,
        data=b"new text",
        request_key="upload-2",
        material_id=str(version.material_id),
        base_revision=1,
    )
    assert upload(context, second, b"new text").status_code == 200
    assert second.number == 2 and second.object_key != version.object_key
    for item, data in [(version, b"self-authored text"), (second, b"new text")]:
        download = client.get(path(project, f"files/{item.pk}/"))
        assert download.status_code == 200
        try:
            assert b"".join(download.streaming_content) == data
            assert "attachment" in download["Content-Disposition"]
            assert download["Cache-Control"] == "no-store"
        finally:
            download.close()
    history = client.get(path(project, f"materials/{version.material_id}/versions/")).data
    assert [item["number"] for item in history["results"]] == [2, 1]


def test_upload_conflicts_and_corrupt_files_are_not_available(context):
    client, project, _ = context
    bad = intent(context, data=b"not a pdf", name="broken.pdf")
    assert upload(context, bad, b"not a pdf").status_code == 400
    bad.refresh_from_db()
    assert bad.status == "failed" and bad.error_code == "invalid_file"
    assert client.get(path(project, f"files/{bad.pk}/")).status_code == 404
    version = intent(context, request_key="text-file")
    assert upload(context, version).status_code == 200
    assert upload(context, version, b"x" * len(b"self-authored text")).status_code == 409
    response = client.post(
        path(project, "uploads/"),
        {
            "request_key": "new-key",
            "material_id": str(version.material_id),
            "base_revision": 0,
            "size": 1,
            "file_name": "v2.txt",
        },
        format="json",
    )
    assert response.status_code == 409
    response = client.post(
        path(project, "uploads/"),
        {
            "request_key": "huge",
            "title": "超限",
            "size": 21 * 1024 * 1024,
            "file_name": "huge.txt",
        },
        format="json",
    )
    assert response.status_code == 400


def test_storage_failure_has_diagnostic_state_and_can_retry(context):
    version = intent(context)
    with patch("core.materials.service.s3_client", side_effect=OSError("private connection")):
        response = upload(context, version)
    assert response.status_code == 503
    version.refresh_from_db()
    assert version.status == "failed" and "private" not in version.error_message
    assert upload(context, version).status_code == 200


def test_object_success_database_failure_reconciles_without_new_version(context):
    version = intent(context)
    with patch(
        "core.materials.service.publish_upload",
        side_effect=RuntimeError("simulated database error"),
    ):
        with pytest.raises(RuntimeError):
            upload(context, version)
    version.refresh_from_db()
    assert version.status == "validating" and version.sha256
    MaterialVersion.objects.filter(pk=version.pk).update(
        lease_until=timezone.now() - timedelta(seconds=1)
    )
    reconcile_upload(version.pk)
    reconcile_upload(version.pk)
    version.refresh_from_db()
    assert version.status == "available" and MaterialVersion.objects.count() == 1


def test_revocation_before_publish_and_unauthorized_download(context):
    client, project, owner = context
    author = get_user_model().objects.create_user(username="upload-coauthor")
    member = ProjectMember.objects.create(project=project, user=author, role="author")
    client.force_authenticate(author)
    version = intent(context)
    from core.materials.service import read_and_verify

    def revoke(storage, item):
        read_and_verify(storage, item)
        member.delete()

    with patch("core.materials.service.read_and_verify", side_effect=revoke):
        assert upload(context, version).status_code == 409
    version.refresh_from_db()
    assert version.status == "failed" and version.error_code == "authorization_changed"
    assert client.get(path(project, f"files/{version.pk}/")).status_code == 404
    client.force_authenticate(owner)
    assert client.get(path(project, f"files/{version.pk}/")).status_code == 404


def test_project_and_role_scope_and_content_is_immutable(context):
    client, project, owner = context
    version = intent(context)
    assert upload(context, version).status_code == 200
    other = Project.objects.create(owner=owner, name="另一个项目")
    assert client.get(path(other, f"files/{version.pk}/")).status_code == 404
    assert client.get(path(other, f"materials/{version.material_id}/versions/")).status_code == 404
    reviewer = get_user_model().objects.create_user(username="upload-reviewer")
    ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
    client.force_authenticate(reviewer)
    assert upload(context, version).status_code == 403
    response = client.get(path(project, f"files/{version.pk}/"))
    assert response.status_code == 200
    response.close()
    assert client.get(path(project, "materials/")).data["count"] == 1


def test_missing_object_during_reconciliation_stays_failed(context):
    _, _, user = context
    version = intent(context)
    claim_upload(user, version.pk, hashlib.sha256(b"self-authored text").hexdigest())
    MaterialVersion.objects.filter(pk=version.pk).update(
        lease_until=timezone.now() - timedelta(seconds=1)
    )
    reconcile_upload(version.pk)
    version.refresh_from_db()
    assert version.status == "failed" and version.error_code == "reconciliation_failed"


def test_self_authored_pdf_and_csv_validation():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    validate_file(stream.getvalue(), "self-authored.pdf")
    validate_file(b"experiment,value\na,1\n", "self-authored.csv")
    from rest_framework.exceptions import ValidationError

    for content, name in [
        (b"a,b\n1\n", "bad.csv"),
        (b"\xff\xfe", "bad.txt"),
        (b"PK\x03\x04", "bad.docx"),
    ]:
        with pytest.raises(ValidationError):
            validate_file(content, name)


def test_concurrent_intents_are_idempotent(context):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    _, project, user = context
    barrier = Barrier(2)

    def submit(_):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=user.pk))
            barrier.wait(timeout=10)
            return client.post(
                path(project, "uploads/"),
                {
                    "request_key": "concurrent",
                    "title": "并发样例",
                    "size": 1,
                    "file_name": "a.txt",
                },
                format="json",
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [200, 201]
    assert MaterialVersion.objects.count() == 1


def test_docx_validation_rejects_xml_entities_and_corruption():
    import zipfile

    from rest_framework.exceptions import ValidationError

    def document(xml):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'wordprocessingml.document.main+xml"/>'
                "</Types>",
            )
            archive.writestr(
                "_rels/.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="word/document.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
                "</Relationships>",
            )
            archive.writestr("word/document.xml", xml)
        return stream.getvalue()

    validate_file(
        document(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>'
        ),
        "self-authored.docx",
    )
    with pytest.raises(ValidationError):
        validate_file(
            document('<!DOCTYPE x [<!ENTITY e SYSTEM "file:///not-readable">]><x>&e;</x>'),
            "bad.docx",
        )


def test_mini_token_upload_is_visible_to_web_account(context):
    from core.accounts.wechat import digest
    from core.models import WechatIdentity, WechatSession

    web, project, user = context
    with override_settings(WECHAT_APP_ID="self-authored-mini"):
        identity = WechatIdentity.objects.create(
            app_id="self-authored-mini", open_id="self-authored", user=user
        )
        WechatSession.objects.create(
            identity=identity,
            user=user,
            token_hash=digest("self-authored-token"),
            expires_at=timezone.now() + timedelta(hours=1),
        )
        mini = APIClient()
        mini.credentials(HTTP_AUTHORIZATION="Bearer self-authored-token")
        version = intent((mini, project, user))
        assert upload((mini, project, user), version).status_code == 200
        assert web.get(path(project, "materials/")).data["results"][0]["id"] == str(
            version.material_id
        )
        download = web.get(path(project, f"files/{version.pk}/"))
        assert b"".join(download.streaming_content) == b"self-authored text"
