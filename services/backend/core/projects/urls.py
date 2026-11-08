from django.urls import path

from core.projects.views import (
    AIPermissionView,
    MemberDetailView,
    MemberListView,
    PolicyListView,
    ProjectDetailView,
    ProjectListView,
)

urlpatterns = [
    path("api/v1/projects/", ProjectListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/", ProjectDetailView.as_view()),
    path("api/v1/projects/<uuid:project_id>/policies/", PolicyListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/members/", MemberListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/members/<int:user_id>/", MemberDetailView.as_view()),
    path("api/v1/projects/<uuid:project_id>/ai-permissions/", AIPermissionView.as_view()),
]
