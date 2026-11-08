from django.urls import path

from core.materials.parse_views import ChunkDetailView, ChunkListView, ParseListView
from core.materials.views import (
    MaterialDownloadView,
    MaterialListView,
    MaterialPreviewView,
    MaterialVersionsView,
    UploadFileView,
    UploadIntentView,
)

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/materials/", MaterialListView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/materials/<uuid:material_id>/versions/",
        MaterialVersionsView.as_view(),
    ),
    path("api/v1/projects/<uuid:project_id>/uploads/", UploadIntentView.as_view()),
    path("api/v1/projects/<uuid:project_id>/uploads/<uuid:version_id>/", UploadFileView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/files/<uuid:version_id>/", MaterialDownloadView.as_view()
    ),
    path(
        "api/v1/projects/<uuid:project_id>/files/<uuid:version_id>/preview/",
        MaterialPreviewView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/files/<uuid:version_id>/parses/", ParseListView.as_view()
    ),
    path("api/v1/projects/<uuid:project_id>/parses/<uuid:run_id>/chunks/", ChunkListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/chunks/<uuid:chunk_id>/", ChunkDetailView.as_view()),
]
