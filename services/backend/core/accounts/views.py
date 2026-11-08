from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.projects.serializers import LoginSerializer


def session_data(request):
    user = request.user
    return {
        "user": {"id": user.pk, "username": user.get_username()} if user.is_authenticated else None,
        "csrf_token": get_token(request),
    }


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class SessionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(session_data(request))

    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate(request, **data.validated_data)
        if user is None:
            return Response({"detail": "账号或密码不正确。"}, status=400)
        login(request, user)
        return Response(session_data(request))


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(session_data(request))
