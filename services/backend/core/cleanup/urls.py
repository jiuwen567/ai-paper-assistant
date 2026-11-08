from django.urls import path

from core.cleanup.views import (
    CleanupCreateView,
    CleanupDetailView,
    CleanupListView,
    CleanupPreviewView,
)

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/cleanup-preview/", CleanupPreviewView.as_view()),
    path("api/v1/projects/<uuid:project_id>/cleanup/", CleanupCreateView.as_view()),
    path("api/v1/cleanups/", CleanupListView.as_view()),
    path("api/v1/cleanups/<uuid:request_id>/", CleanupDetailView.as_view()),
]
