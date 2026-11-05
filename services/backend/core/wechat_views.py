from django.conf import settings
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import require_active_user
from core.models import WechatIdentity, WechatSession
from core.projects import validated
from core.wechat import bind_account, exchange_code, login_wechat, unbind_account
from core.wechat_auth import WechatAuthentication


class LoginCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=256)


class BindingCodeSerializer(serializers.Serializer):
    code = serializers.RegexField(r"^[A-Fa-f0-9]{24}$")


@method_decorator(never_cache, name="dispatch")
class WechatLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        data = validated(LoginCodeSerializer, request)
        return Response(login_wechat(exchange_code(data["code"])))


@method_decorator(never_cache, name="dispatch")
class WechatBindingView(APIView):
    # 必须在已登录的 Web Session 下确认，不能凭小程序 token 绑定其他内部账号。
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        require_active_user(request.user)
        identity = WechatIdentity.objects.filter(
            app_id=settings.WECHAT_APP_ID,
            user=request.user,
        ).first()
        return Response({"bound": identity is not None})

    def post(self, request):
        require_active_user(request.user)
        code = validated(BindingCodeSerializer, request)["code"].upper()
        bind_account(request.user, code)
        return Response({"bound": True})

    def delete(self, request):
        require_active_user(request.user)
        unbind_account(request.user)
        return Response({"bound": False})


class WechatLogoutView(APIView):
    authentication_classes = [WechatAuthentication]

    def post(self, request):
        WechatSession.objects.filter(pk=request.auth.pk).update(revoked_at=timezone.now())
        return Response({"logged_out": True})


class WechatUnbindView(APIView):
    authentication_classes = [WechatAuthentication]

    def post(self, request):
        unbind_account(request.user, request.auth.identity_id)
        return Response({"bound": False})
