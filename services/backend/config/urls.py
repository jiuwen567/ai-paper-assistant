from django.urls import path

from core.accounts import LogoutView, SessionView
from core.job_views import JobControlView, JobDetailView, JobListView
from core.material_views import (
    MaterialDownloadView,
    MaterialListView,
    MaterialPreviewView,
    MaterialVersionsView,
    UploadFileView,
    UploadIntentView,
)
from core.parse_views import ChunkDetailView, ChunkListView, ParseListView
from core.projects import (
    AIPermissionView,
    MemberDetailView,
    MemberListView,
    PolicyListView,
    ProjectDetailView,
    ProjectListView,
)
from core.views import LiveView, ReadyView
from core.wechat_views import (
    WechatBindingView,
    WechatLoginView,
    WechatLogoutView,
    WechatUnbindView,
)

urlpatterns = [
    path("api/v1/auth/wechat/login/", WechatLoginView.as_view()),
    path("api/v1/auth/wechat/binding/", WechatBindingView.as_view()),
    path("api/v1/auth/wechat/logout/", WechatLogoutView.as_view()),
    path("api/v1/auth/wechat/unbind/", WechatUnbindView.as_view()),
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
    path("api/v1/health/live/", LiveView.as_view(), name="health-live"),
    path("api/v1/health/ready/", ReadyView.as_view(), name="health-ready"),
]
