from django.urls import path

from core.disclosures.views import (
    DisclosureHistoryView,
    DisclosureRevisionView,
    DisclosureView,
    UsageDetailView,
    UsageListView,
)

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/usage/", UsageListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/usage/<uuid:job_id>/", UsageDetailView.as_view()),
    path("api/v1/projects/<uuid:project_id>/disclosure/", DisclosureView.as_view()),
    path("api/v1/projects/<uuid:project_id>/disclosure/history/", DisclosureHistoryView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/disclosure/history/<int:number>/",
        DisclosureRevisionView.as_view(),
    ),
]
