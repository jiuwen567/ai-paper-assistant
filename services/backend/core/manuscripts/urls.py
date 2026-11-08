from django.urls import path

from core.manuscripts.views import (
    ManuscriptDiffView,
    ManuscriptHistoryView,
    ManuscriptImportPreviewView,
    ManuscriptImportsView,
    ManuscriptRestoreView,
    ManuscriptRevisionView,
    ManuscriptView,
)

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/manuscript/", ManuscriptView.as_view()),
    path("api/v1/projects/<uuid:project_id>/manuscript/history/", ManuscriptHistoryView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/manuscript/history/<int:number>/",
        ManuscriptRevisionView.as_view(),
    ),
    path("api/v1/projects/<uuid:project_id>/manuscript/diff/", ManuscriptDiffView.as_view()),
    path("api/v1/projects/<uuid:project_id>/manuscript/restore/", ManuscriptRestoreView.as_view()),
    path("api/v1/projects/<uuid:project_id>/manuscript/imports/", ManuscriptImportsView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/manuscript/imports/<uuid:parse_id>/",
        ManuscriptImportPreviewView.as_view(),
    ),
]
