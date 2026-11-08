from django.urls import path

from core.system.views import LiveView, ReadyView

urlpatterns = [
    path("api/v1/health/live/", LiveView.as_view(), name="health-live"),
    path("api/v1/health/ready/", ReadyView.as_view(), name="health-ready"),
]
