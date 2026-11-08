from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from core.accounts.wechat import digest
from core.models import WechatSession


class WechatAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != b"bearer":
            return None
        if len(header) != 2 or len(header[1]) > 128:
            raise AuthenticationFailed("请重新登录小程序。")
        try:
            token = header[1].decode("ascii")
        except UnicodeDecodeError:
            raise AuthenticationFailed("请重新登录小程序。") from None
        session = (
            WechatSession.objects.select_related("identity", "user")
            .filter(
                token_hash=digest(token),
                revoked_at=None,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if (
            session is None
            or not session.user.is_active
            or session.identity.user_id != session.user_id
            or session.identity.app_id != settings.WECHAT_APP_ID
        ):
            raise AuthenticationFailed("小程序登录已过期或解绑，请重新登录。")
        return session.user, session

    def authenticate_header(self, request):
        return "Bearer"
