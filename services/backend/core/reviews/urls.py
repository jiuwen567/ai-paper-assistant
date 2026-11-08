from django.urls import path

from core.reviews.views import (
    ReviewDetailView,
    ReviewFindingsView,
    ReviewFindingView,
    ReviewListView,
    ReviewTaskView,
)

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/reviews/", ReviewListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/reviews/tasks/", ReviewTaskView.as_view()),
    path("api/v1/projects/<uuid:project_id>/reviews/<uuid:review_id>/", ReviewDetailView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/reviews/<uuid:review_id>/findings/",
        ReviewFindingsView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/review-findings/<uuid:finding_id>/",
        ReviewFindingView.as_view(),
    ),
]
