from django.urls import path

from core.accounts import LogoutView, SessionView
from core.job_views import JobControlView, JobDetailView, JobListView
from core.projects import (
    AIPermissionView,
    MemberDetailView,
    MemberListView,
    PolicyListView,
    ProjectDetailView,
    ProjectListView,
)
from core.views import LiveView, ReadyView

urlpatterns = [
    path("api/v1/auth/session/", SessionView.as_view()),
    path("api/v1/auth/logout/", LogoutView.as_view()),
    path("api/v1/projects/", ProjectListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/", ProjectDetailView.as_view()),
    path("api/v1/projects/<uuid:project_id>/policies/", PolicyListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/members/", MemberListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/members/<int:user_id>/", MemberDetailView.as_view()),
    path("api/v1/projects/<uuid:project_id>/ai-permissions/", AIPermissionView.as_view()),
    path("api/v1/projects/<uuid:project_id>/jobs/", JobListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/jobs/<uuid:job_id>/", JobDetailView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/jobs/<uuid:job_id>/<str:action>/",
        JobControlView.as_view(),
    ),
    path("api/v1/health/live/", LiveView.as_view(), name="health-live"),
    path("api/v1/health/ready/", ReadyView.as_view(), name="health-ready"),
]
