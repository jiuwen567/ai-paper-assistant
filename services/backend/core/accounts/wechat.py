import hashlib
import json
import secrets
from datetime import timedelta
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, AuthenticationFailed, ValidationError

from core.models import WechatBinding, WechatIdentity, WechatSession
from core.projects.access import VersionConflict


class WechatUnavailable(APIException):
    status_code = 503
    default_detail = "微信登录暂不可用，请稍后重试。"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def exchange_code(code):
    if not settings.WECHAT_APP_ID or not settings.WECHAT_APP_SECRET:
        raise WechatUnavailable("服务端尚未配置微信登录。")
    query = urlencode(
        {
            "appid": settings.WECHAT_APP_ID,
            "secret": settings.WECHAT_APP_SECRET,
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )
    try:
        with urlopen(
            f"https://api.weixin.qq.com/sns/jscode2session?{query}", timeout=8
        ) as response:
            result = json.loads(response.read(16384))
    except (URLError, TimeoutError, ValueError, OSError):
        # URL 含 AppSecret，绝不返回或记录底层异常。
        raise WechatUnavailable() from None
    if not isinstance(result, dict):
        raise WechatUnavailable()
    if result.get("errcode") in [-1, 45011]:
        raise WechatUnavailable()
    if result.get("errcode", 0) != 0:
        raise ValidationError("微信登录凭证无效或已过期，请重新登录。")
    open_id = result.get("openid")
    if not isinstance(open_id, str) or not open_id or len(open_id) > 128:
        raise WechatUnavailable()
    return open_id


@transaction.atomic
def login_wechat(open_id):
    identity, _ = WechatIdentity.objects.get_or_create(
        app_id=settings.WECHAT_APP_ID,
        open_id=open_id,
    )
    identity = WechatIdentity.objects.select_for_update().get(pk=identity.pk)
    if identity.user_id is None:
        # 每次重新登录废弃此前未使用的码；数据库仅保存摘要。
        WechatBinding.objects.filter(identity=identity, used_at=None).update(used_at=timezone.now())
        code = secrets.token_hex(12).upper()
        expires = timezone.now() + timedelta(minutes=5)
        WechatBinding.objects.create(identity=identity, code_hash=digest(code), expires_at=expires)
        return {"bound": False, "binding_code": code, "expires_at": expires}
    user = get_user_model().objects.get(pk=identity.user_id)
    if not user.is_active:
        raise AuthenticationFailed("账号已停用。")
    token = secrets.token_urlsafe(32)
    expires = timezone.now() + timedelta(days=7)
    WechatSession.objects.create(
        identity=identity,
        user=user,
        token_hash=digest(token),
        expires_at=expires,
    )
    return {
        "bound": True,
        "token": token,
        "expires_at": expires,
        "user": {"id": user.pk, "username": user.get_username()},
    }


@transaction.atomic
def bind_account(user, code):
    binding = WechatBinding.objects.filter(code_hash=digest(code)).first()
    if binding is None:
        raise ValidationError("绑定码无效、过期或已使用。")
    identity = WechatIdentity.objects.select_for_update().get(pk=binding.identity_id)
    binding.refresh_from_db()
    if binding.used_at or binding.expires_at <= timezone.now():
        raise VersionConflict("绑定码无效、过期或已使用。")
    if identity.app_id != settings.WECHAT_APP_ID:
        raise ValidationError("绑定码不属于当前微信应用。")
    # 同一内部用户在每个 AppID 仅允许一个身份；锁用户以处理不同码并发绑定。
    current = get_user_model().objects.select_for_update().get(pk=user.pk)
    if not current.is_active:
        raise AuthenticationFailed("账号已停用。")
    if identity.user_id is not None:
        raise VersionConflict("该微信身份已绑定账号，请先解绑。")
    if WechatIdentity.objects.filter(app_id=identity.app_id, user=current).exists():
        raise VersionConflict("当前账号已绑定微信，请先解绑。")
    identity.user = current
    identity.bound_at = timezone.now()
    identity.save()
    WechatBinding.objects.filter(identity=identity, used_at=None).update(used_at=timezone.now())


@transaction.atomic
def unbind_account(user, identity_id=None):
    identities = WechatIdentity.objects.select_for_update().filter(
        app_id=settings.WECHAT_APP_ID,
        user=user,
    )
    if identity_id is not None:
        identities = identities.filter(pk=identity_id)
    for identity in identities:
        WechatSession.objects.filter(identity=identity, revoked_at=None).update(
            revoked_at=timezone.now()
        )
        WechatBinding.objects.filter(identity=identity, used_at=None).update(used_at=timezone.now())
        identity.user = None
        identity.bound_at = None
        identity.save()
