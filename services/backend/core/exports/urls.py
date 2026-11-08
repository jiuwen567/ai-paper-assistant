from django.urls import path

from core.exports.views import (
    ExportDetailView,
    ExportDownloadView,
    ExportPreviewView,
    ExportsView,
    ExportTemplatesView,
)

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/export-templates/", ExportTemplatesView.as_view()),
    path("api/v1/projects/<uuid:project_id>/exports/preview/", ExportPreviewView.as_view()),
    path("api/v1/projects/<uuid:project_id>/exports/", ExportsView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/exports/<uuid:snapshot_id>/", ExportDetailView.as_view()
    ),
    path(
        "api/v1/projects/<uuid:project_id>/exports/<uuid:snapshot_id>/download/",
        ExportDownloadView.as_view(),
    ),
]
