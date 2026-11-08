from django.urls import path

from core.graph.evidence_views import EvidenceLinkHistoryView, EvidenceLinksView, EvidenceLinkView
from core.graph.views import GraphPathsView, GraphRebuildView

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/evidence-links/", EvidenceLinksView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/evidence-links/<uuid:link_id>/",
        EvidenceLinkView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/evidence-links/<uuid:link_id>/history/",
        EvidenceLinkHistoryView.as_view(),
    ),
    path("api/v1/projects/<uuid:project_id>/graph/paths/", GraphPathsView.as_view()),
    path("api/v1/projects/<uuid:project_id>/graph/rebuild/", GraphRebuildView.as_view()),
]
