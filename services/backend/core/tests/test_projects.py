"""自制账号与项目；全部在 pytest-django 独立 PostgreSQL 测试库中运行。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from django.http import Http404
from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied
from rest_framework.test import APIClient

from core.access import require_ai_action, require_project_resource
from core.models import Project, ProjectMember, ProjectPolicy

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def users():
    return {
        name: get_user_model().objects.create_user(username=name, password="test-only-password")
        for name in ["owner", "author", "reviewer", "outsider"]
    }


@pytest.fixture
def clients(users):
    clients = {}
    for name, user in users.items():
        client = APIClient()
        client.force_authenticate(user=user)
        clients[name] = client
    return clients


@pytest.fixture
def project(clients, users):
    response = clients["owner"].post(
        "/api/v1/projects/", {"name": "自制测试论文", "paper_type": "课程论文"}, format="json"
    )
    assert response.status_code == 201
    project = Project.objects.get(pk=response.data["id"])
    for role in ["author", "reviewer"]:
        ProjectMember.objects.create(project=project, user=users[role], role=role)
    return project


def path(project, suffix=""):
    return f"/api/v1/projects/{project.pk}/{suffix}"


def policy_data(**changes):
    return {
        "version": 1,
        "source": "自制课程规则",
        "source_version": "2026-v1",
        "notes": "允许阅读，不允许表达建议。",
        "verified": True,
        "allowed_actions": ["reading"],
        **changes,
    }


def test_session_login_logout_and_csrf(users):
    client = APIClient(enforce_csrf_checks=True)
    info = client.get("/api/v1/auth/session/")
    assert info.data["user"] is None
    assert "no-store" in info["Cache-Control"]
    credentials = {"username": "owner", "password": "test-only-password"}
    assert client.post("/api/v1/auth/session/", credentials).status_code == 403
    client.credentials(HTTP_X_CSRFTOKEN=info.data["csrf_token"])
    assert (
        client.post("/api/v1/auth/session/", {**credentials, "password": "bad"}).status_code == 400
    )
    response = client.post("/api/v1/auth/session/", credentials)
    assert response.status_code == 200
    assert response.data["user"]["id"] == users["owner"].pk
    assert client.get("/api/v1/auth/session/").data["user"]["username"] == "owner"
    # 登录旋转 CSRF token，旧 token 不能写入。
    assert client.post("/api/v1/projects/", {"name": "测试"}).status_code == 403
    client.credentials(HTTP_X_CSRFTOKEN=response.data["csrf_token"])
    assert client.post("/api/v1/projects/", {"name": "测试"}).status_code == 201
    client.credentials()
    assert client.post("/api/v1/auth/logout/").status_code == 403
    client.credentials(HTTP_X_CSRFTOKEN=response.data["csrf_token"])
    assert client.post("/api/v1/auth/logout/").status_code == 200
    assert client.get("/api/v1/projects/").status_code == 403


def test_login_rejects_foreign_origin_and_inactive_account(users):
    client = APIClient(enforce_csrf_checks=True)
    token = client.get("/api/v1/auth/session/").data["csrf_token"]
    client.credentials(HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://untrusted.example")
    credentials = {"username": "owner", "password": "test-only-password"}
    assert client.post("/api/v1/auth/session/", credentials).status_code == 403
    client.credentials(HTTP_X_CSRFTOKEN=token)
    users["owner"].is_active = False
    users["owner"].save()
    assert client.post("/api/v1/auth/session/", credentials).status_code == 400


def test_project_creation_atomic_defaults_and_owner_not_client_controlled(clients, users):
    response = clients["owner"].post(
        "/api/v1/projects/",
        {
            "name": "自制论文",
            "paper_type": "毕业论文",
            "requirements": "按自制课程要求",
            "template": "department-default",
            "owner": users["outsider"].pk,
            "policy": {"verified": True, "allowed_actions": ["expression"]},
        },
        format="json",
    )
    assert response.status_code == 201
    data = response.data
    assert data["owner_name"] == "owner"
    assert data["policy"]["version"] == 1
    assert data["policy"]["verified"] is False
    assert data["policy"]["allowed_actions"] == []
    assert data["requirements"] == "按自制课程要求"
    assert data["template"] == "department-default"
    assert clients["owner"].post("/api/v1/projects/", {"name": " "}).status_code == 400
    assert Project.objects.count() == ProjectPolicy.objects.count() == 1


def test_list_filters_projects_and_paginates(clients, project):
    assert clients["outsider"].get("/api/v1/projects/").data["count"] == 0
    for name in ["owner", "author", "reviewer"]:
        response = clients[name].get("/api/v1/projects/")
        assert response.data["count"] == 1
        assert response.data["results"][0]["role"] == (
            "reviewer" if name == "reviewer" else "author"
        )
    for i in range(21):
        clients["outsider"].post("/api/v1/projects/", {"name": f"测试项目 {i}"})
    response = clients["outsider"].get("/api/v1/projects/")
    assert response.data["count"] == 21
    assert len(response.data["results"]) == 20
    assert response.data["next"] is not None
    assert len(clients["outsider"].get("/api/v1/projects/?page=2").data["results"]) == 1


@pytest.mark.parametrize(
    "method,suffix,data",
    [
        ("get", "", None),
        ("patch", "", {"name": "越权", "version": 1}),
        ("get", "policies/", None),
        ("post", "policies/", policy_data()),
        ("get", "members/", None),
        ("post", "members/", {"username": "outsider", "role": "author", "version": 1}),
        ("delete", "members/1/", {"version": 1}),
        ("post", "ai-permissions/", {"action": "reading", "policy_version": 1}),
    ],
)
def test_unauthenticated_and_cross_project_requests_denied(clients, project, method, suffix, data):
    for client, status in [(APIClient(), 403), (clients["outsider"], 404)]:
        response = getattr(client, method)(path(project, suffix), data, format="json")
        assert response.status_code == status
        if status == 404:
            missing_url = path(project, suffix).replace(str(project.pk), str(uuid4()))
            missing = getattr(client, method)(missing_url, data, format="json")
            assert missing.status_code == 404
            assert missing.json() == response.json() == {"detail": "项目不存在。"}
    project.refresh_from_db()
    assert project.version == 1
    assert project.name == "自制测试论文"


def test_author_edit_and_stale_replay(clients, project):
    payload = {"version": 1, "name": "修订标题", "requirements": "新的写作要求"}
    response = clients["author"].patch(path(project), payload, format="json")
    assert response.status_code == 200
    assert response.data["version"] == 2
    assert clients["owner"].patch(path(project), payload, format="json").status_code == 409
    assert clients["owner"].patch(path(project), {"name": "无版本"}).status_code == 400
    project.refresh_from_db()
    assert project.name == "修订标题"
    assert project.version == 2


@pytest.mark.parametrize(
    "suffix,data",
    [
        ("", {"version": 1, "name": "越权"}),
        ("policies/", policy_data()),
        ("members/", {"version": 1, "username": "outsider", "role": "author"}),
        ("ai-permissions/", {"policy_version": 1, "action": "reading"}),
    ],
)
def test_reviewer_read_only(clients, project, suffix, data):
    assert clients["reviewer"].get(path(project)).status_code == 200
    method = "patch" if not suffix else "post"
    assert (
        getattr(clients["reviewer"], method)(path(project, suffix), data, format="json").status_code
        == 403
    )


def test_members_owner_only_roles_and_revocation(clients, project, users):
    data = {"version": 1, "username": "outsider", "role": "author"}
    assert clients["author"].post(path(project, "members/"), data).status_code == 403
    assert (
        clients["owner"].post(path(project, "members/"), {**data, "role": "owner"}).status_code
        == 400
    )
    assert (
        clients["owner"].post(path(project, "members/"), {**data, "username": "owner"}).status_code
        == 400
    )
    assert clients["owner"].post(path(project, "members/"), data).status_code == 200
    assert clients["owner"].post(path(project, "members/"), data).status_code == 409
    assert clients["outsider"].get(path(project)).status_code == 200
    # 重复添加改为更新角色，不产生重复成员。
    data.update(version=2, role="reviewer")
    assert clients["owner"].post(path(project, "members/"), data).status_code == 200
    assert ProjectMember.objects.filter(project=project, user=users["outsider"]).count() == 1
    assert (
        clients["outsider"].patch(path(project), {"version": 3, "name": "越权"}).status_code == 403
    )
    member_url = path(project, f"members/{users['outsider'].pk}/")
    assert clients["owner"].delete(member_url, {"version": 3}, format="json").status_code == 200
    assert clients["outsider"].get(path(project)).status_code == 404
    assert clients["outsider"].get("/api/v1/projects/").data["count"] == 0
    assert clients["owner"].delete(member_url, {"version": 3}, format="json").status_code == 409


def test_rules_default_deny_history_disable_and_stale_version(clients, project):
    gate = path(project, "ai-permissions/")
    request = {"action": "reading", "policy_version": 1}
    assert clients["owner"].post(gate, request).status_code == 403
    response = clients["author"].post(path(project, "policies/"), policy_data(), format="json")
    assert response.status_code == 201
    assert response.data["policy"]["version"] == 2
    assert clients["owner"].post(gate, request).status_code == 409
    request["policy_version"] = 2
    assert clients["author"].post(gate, request).status_code == 200
    assert clients["author"].post(gate, {**request, "action": "expression"}).status_code == 403
    assert clients["author"].post(gate, {**request, "action": "write_paper"}).status_code == 400
    assert clients["author"].post(gate, {"action": "reading"}).status_code == 400
    assert (
        clients["owner"].post(path(project, "policies/"), policy_data(), format="json").status_code
        == 409
    )
    disabled = policy_data(version=2, verified=False, allowed_actions=[])
    assert (
        clients["owner"].post(path(project, "policies/"), disabled, format="json").status_code
        == 201
    )
    assert clients["author"].post(gate, request).status_code == 409
    assert clients["author"].post(gate, {**request, "policy_version": 3}).status_code == 403
    history = clients["reviewer"].get(path(project, "policies/")).data["results"]
    assert [item["version"] for item in history] == [3, 2, 1]
    assert history[1]["allowed_actions"] == ["reading"]
    assert history[1]["created_by"] == "author"


@pytest.mark.parametrize(
    "changes",
    [
        {"verified": False},
        {"source": " "},
        {"source_version": ""},
        {"allowed_actions": ["write_paper"]},
        {"allowed_actions": "reading"},
    ],
)
def test_invalid_rules_never_change_current_policy(clients, project, changes):
    response = clients["owner"].post(
        path(project, "policies/"), policy_data(**changes), format="json"
    )
    assert response.status_code == 400
    project.refresh_from_db()
    assert project.version == 1
    assert project.policies.count() == 1


def test_resource_lookup_checks_both_project_and_resource_id(clients, project, users):
    other = clients["owner"].post("/api/v1/projects/", {"name": "另一项目"}).data
    own_policy = project.policies.get()
    assert (
        require_project_resource(
            users["author"], project.pk, ProjectPolicy.objects.all(), own_policy.pk
        )
        == own_policy
    )
    # 即使两个项目都获授权，也不能把其他项目的资源 ID 嵌入当前项目。
    with pytest.raises(Http404):
        require_project_resource(
            users["owner"], project.pk, ProjectPolicy.objects.all(), other["policy"]["id"]
        )
    with pytest.raises(NotFound):
        require_project_resource(
            users["outsider"], project.pk, ProjectPolicy.objects.all(), own_policy.pk
        )
    with pytest.raises(PermissionDenied):
        require_project_resource(
            users["reviewer"], project.pk, ProjectPolicy.objects.all(), own_policy.pk, write=True
        )


def test_worker_gate_reloads_membership_and_user_state(clients, project, users):
    clients["owner"].post(path(project, "policies/"), policy_data(), format="json")
    user_snapshot = users["author"]
    assert require_ai_action(user_snapshot, project.pk, "reading", 2).version == 2
    ProjectMember.objects.filter(project=project, user=user_snapshot).update(role="reviewer")
    with pytest.raises(PermissionDenied):
        require_ai_action(user_snapshot, project.pk, "reading", 2)
    ProjectMember.objects.filter(project=project, user=user_snapshot).delete()
    with pytest.raises(NotFound):
        require_ai_action(user_snapshot, project.pk, "reading", 2)
    get_user_model().objects.filter(pk=users["owner"].pk).update(is_active=False)
    with pytest.raises(NotAuthenticated):
        require_ai_action(users["owner"], project.pk, "reading", 2)


def test_database_constraints(project, users):
    invalid_creates = [
        lambda: ProjectMember.objects.create(project=project, user=users["author"], role="author"),
        lambda: ProjectMember.objects.create(project=project, user=users["outsider"], role="owner"),
        lambda: ProjectPolicy.objects.create(project=project, version=1, created_by=users["owner"]),
        lambda: ProjectPolicy.objects.create(
            project=project, version=2, created_by=users["owner"], allowed_actions=["reading"]
        ),
        lambda: ProjectPolicy.objects.create(
            project=project, version=2, created_by=users["owner"], verified=True
        ),
    ]
    for create in invalid_creates:
        with pytest.raises(IntegrityError), transaction.atomic():
            create()


@pytest.mark.django_db(transaction=True)
def test_concurrent_policy_updates_have_one_winner(project, users):
    barrier = Barrier(2)

    def update():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=get_user_model().objects.get(pk=users["owner"].pk))
            barrier.wait(timeout=10)
            return client.post(path(project, "policies/"), policy_data(), format="json").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: update(), range(2)))
    assert sorted(results) == [201, 409]
    assert project.policies.count() == 2
    project.refresh_from_db()
    assert project.version == 2
