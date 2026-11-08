from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.system.health import readiness


class LiveView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "api", "version": "0.1.0"})


class ReadyView(LiveView):
    def get(self, request):
        result = readiness()
        return Response(result, status=200 if result["status"] == "ok" else 503)
