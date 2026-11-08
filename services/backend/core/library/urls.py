from django.urls import path

from core.library.views import (
    BibliographyView,
    EvidenceDetailView,
    EvidenceListView,
    MaterialStateView,
)

urlpatterns = [
    path(
        "api/v1/projects/<uuid:project_id>/files/<uuid:version_id>/bibliography/",
        BibliographyView.as_view(),
    ),
    path("api/v1/projects/<uuid:project_id>/evidence/", EvidenceListView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/evidence/<uuid:evidence_id>/",
        EvidenceDetailView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/materials/<uuid:material_id>/state/",
        MaterialStateView.as_view(),
    ),
]
