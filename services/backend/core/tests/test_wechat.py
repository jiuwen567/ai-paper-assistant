"""微信接口返回值使用自制模拟，账号、绑定、权限和冲突使用真实 PostgreSQL。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.accounts.wechat import (
    WechatUnavailable,
    bind_account,
    digest,
    exchange_code,
    login_wechat,
)
from core.models import Project, ProjectPolicy, WechatBinding, WechatIdentity, WechatSession

pytestmark = [pytest.mark.integration, pytest.mark.django_db]
BASE = "/api/v1/auth/wechat/"


@pytest.fixture(autouse=True)
def wechat_settings():
    with override_settings(WECHAT_APP_ID="self-authored-app", WECHAT_APP_SECRET="test-only-secret"):
        yield


@pytest.fixture
def account():
    user = get_user_model().objects.create_user(username="wechat-author", password="test-password")
    web = APIClient(enforce_csrf_checks=True)
    token = web.get("/api/v1/auth/session/").data["csrf_token"]
    response = web.post(
        "/api/v1/auth/session/",
        {
            "username": user.username,
            "password": "test-password",
        },
        HTTP_X_CSRFTOKEN=token,
    )
    web.credentials(HTTP_X_CSRFTOKEN=response.data["csrf_token"])
    project = Project.objects.create(owner=user, name="自制微信联调项目")
    ProjectPolicy.objects.create(project=project, version=1, created_by=user)
    return user, web, project


def mini_login(open_id="self-authored-openid"):
    with patch("core.accounts.wechat_views.exchange_code", return_value=open_id):
        return APIClient().post(BASE + "login/", {"code": "self-authored-code"})


def bind(account, open_id="self-authored-openid"):
    _, web, _ = account
    code = mini_login(open_id).data["binding_code"]
    assert web.post(BASE + "binding/", {"code": code}).status_code == 200
    response = mini_login(open_id)
    mini = APIClient()
    mini.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['token']}")
    return mini, response.data["token"]


def test_web_confirm_and_mini_share_project(account):
    user, web, project = account
    result = mini_login()
    assert result.data["bound"] is False
    assert "no-store" in result["Cache-Control"]
    code = result.data["binding_code"]
    assert WechatBinding.objects.get().code_hash == digest(code)
    assert not WechatSession.objects.exists()
    assert web.post(BASE + "binding/", {"code": code.lower()}).data == {"bound": True}
    login = mini_login()
    assert login.data["user"]["id"] == user.pk
    assert set(login.data) == {"bound", "token", "expires_at", "user"}
    mini = APIClient()
    mini.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['token']}")
    assert mini.get("/api/v1/projects/").data["results"][0]["id"] == str(project.pk)
    assert mini.get(f"/api/v1/projects/{project.pk}/jobs/").status_code == 200
    assert WechatSession.objects.get().token_hash != login.data["token"]
    assert web.get(BASE + "binding/").data == {"bound": True}


def test_binding_requires_web_session_and_csrf(account):
    _, web, _ = account
    code = mini_login().data["binding_code"]
    assert APIClient().post(BASE + "binding/", {"code": code}).status_code == 403
    web.credentials()
    assert web.post(BASE + "binding/", {"code": code}).status_code == 403
    assert WechatIdentity.objects.get().user_id is None


def test_used_expired_and_superseded_code_rejected(account):
    _, web, _ = account
    old = mini_login().data["binding_code"]
    current = mini_login().data["binding_code"]
    assert web.post(BASE + "binding/", {"code": old}).status_code == 409
    WechatBinding.objects.filter(code_hash=digest(current)).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert web.post(BASE + "binding/", {"code": current}).status_code == 409
    code = mini_login().data["binding_code"]
    assert web.post(BASE + "binding/", {"code": code}).status_code == 200
    assert web.post(BASE + "binding/", {"code": code}).status_code == 409
    assert WechatIdentity.objects.get().user_id == account[0].pk


def test_account_conflict_and_application_scope(account):
    _, web, _ = account
    bind(account)
    code = mini_login("second-self-authored-openid").data["binding_code"]
    assert web.post(BASE + "binding/", {"code": code}).status_code == 409
    # 不同 AppID 的相同 OpenID 也不合并。
    with override_settings(WECHAT_APP_ID="other-self-authored-app"):
        other = mini_login().data["binding_code"]
    assert web.post(BASE + "binding/", {"code": other}).status_code == 400
    assert WechatIdentity.objects.count() == 3


@pytest.mark.parametrize("action", ["web_unbind", "mini_unbind", "logout", "expiry", "inactive"])
def test_revocation_and_expiry_reject_old_token(account, action):
    user, web, _ = account
    mini, token = bind(account)
    if action == "web_unbind":
        assert web.delete(BASE + "binding/").status_code == 200
        assert web.delete(BASE + "binding/").status_code == 200
    elif action == "mini_unbind":
        assert mini.post(BASE + "unbind/").status_code == 200
    elif action == "logout":
        assert mini.post(BASE + "logout/").status_code == 200
    elif action == "expiry":
        WechatSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    else:
        user.is_active = False
        user.save()
    assert mini.get("/api/v1/projects/").status_code in [401, 403]
    if action in ["web_unbind", "mini_unbind"]:
        # 旧会话在重新绑定同一账号后也不能复活。
        new_mini, _ = bind(account)
        assert new_mini.get("/api/v1/projects/").status_code == 200
        assert mini.get("/api/v1/projects/").status_code in [401, 403]
        assert WechatSession.objects.get(token_hash=digest(token)).revoked_at


def test_token_cannot_bind_and_cross_project_isolation(account):
    mini, _ = bind(account)
    assert mini.post(BASE + "binding/", {"code": "A" * 24}).status_code == 403
    other_user = get_user_model().objects.create_user(username="other-author")
    other = Project.objects.create(owner=other_user, name="其他项目")
    assert mini.get(f"/api/v1/projects/{other.pk}/").status_code == 404


def test_code_exchange_uses_server_secret_and_discards_session_key():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = (
        b'{"openid":"test-openid","session_key":"private","unionid":"not-used"}'
    )
    with patch("core.accounts.wechat.urlopen", return_value=response) as send:
        assert exchange_code("test-code") == "test-openid"
        url = send.call_args.args[0]
        assert url.startswith("https://api.weixin.qq.com/sns/jscode2session?")
        assert "js_code=test-code" in url and "secret=test-only-secret" in url


@pytest.mark.parametrize("reply", [b"{}", b"[]", b"not-json", b'{"errcode":45011}'])
def test_bad_wechat_response_has_safe_error(reply):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = reply
    with (
        patch("core.accounts.wechat.urlopen", return_value=response),
        pytest.raises(WechatUnavailable),
    ):
        exchange_code("test-code")


def test_missing_configuration_and_transport_errors_do_not_leak():
    with override_settings(WECHAT_APP_SECRET=""):
        response = APIClient().post(BASE + "login/", {"code": "test-code"})
        assert response.status_code == 503
    with patch("core.accounts.wechat.urlopen", side_effect=OSError("secret-url")):
        response = APIClient().post(BASE + "login/", {"code": "test-code"})
        assert response.status_code == 503 and "secret-url" not in str(response.data)


@pytest.mark.django_db(transaction=True)
def test_concurrent_redemption_has_one_winner(account):
    user, _, _ = account
    other = get_user_model().objects.create_user(username="other-account")
    code = login_wechat("concurrent-test-openid")["binding_code"]
    barrier = Barrier(2)

    def redeem(user_id):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                bind_account(get_user_model().objects.get(pk=user_id), code)
                return 200
            except Exception as error:
                return getattr(error, "status_code", 500)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(redeem, [user.pk, other.pk])) == [200, 409]


def test_menu_configuration_has_real_route_without_publishing():
    import json
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    output = StringIO()
    call_command("wechat_menu", web_url="https://self-authored.example", stdout=output)
    menu = json.loads(output.getvalue())
    assert menu["button"][0]["pagepath"] == "pages/projects/projects"
    assert menu["button"][1]["url"] == "https://self-authored.example/wechat"
    assert "test-only-secret" not in output.getvalue()
    with pytest.raises(CommandError):
        call_command("wechat_menu", web_url="http://invalid.example")
