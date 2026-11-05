from django.urls import path

from core.accounts import LogoutView, SessionView
from core.ai_views import AITaskView, AITraceView
from core.expression_views import (
    ExpressionTaskView,
    SuggestionDecisionView,
    SuggestionDetailView,
    SuggestionListView,
    SuggestionPreviewView,
)
from core.job_views import JobControlView, JobDetailView, JobListView
from core.library_views import (
    BibliographyView,
    EvidenceDetailView,
    EvidenceListView,
    MaterialStateView,
)
from core.manuscript_views import (
    ManuscriptDiffView,
    ManuscriptHistoryView,
    ManuscriptImportPreviewView,
    ManuscriptImportsView,
    ManuscriptRestoreView,
    ManuscriptRevisionView,
    ManuscriptView,
)
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
from core.reading_views import (
    ReadingDetailView,
    ReadingListView,
    ReadingSourceView,
    ReadingTaskView,
)
from core.review_views import (
    ReviewDetailView,
    ReviewFindingsView,
    ReviewFindingView,
    ReviewListView,
    ReviewTaskView,
)
from core.search_views import IndexListView, SearchView
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
    path("api/v1/projects/<uuid:project_id>/ai-tasks/", AITaskView.as_view()),
    path("api/v1/projects/<uuid:project_id>/expressions/tasks/", ExpressionTaskView.as_view()),
    path("api/v1/projects/<uuid:project_id>/suggestions/", SuggestionListView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/suggestions/<uuid:suggestion_id>/",
        SuggestionDetailView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/suggestions/<uuid:suggestion_id>/decision/",
        SuggestionDecisionView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/suggestions/<uuid:suggestion_id>/preview/",
        SuggestionPreviewView.as_view(),
    ),
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
    path("api/v1/projects/<uuid:project_id>/reading/", ReadingListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/reading/tasks/", ReadingTaskView.as_view()),
    path("api/v1/projects/<uuid:project_id>/reading/sources/", ReadingSourceView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/reading/<uuid:record_id>/", ReadingDetailView.as_view()
    ),
    path("api/v1/projects/<uuid:project_id>/ai-tasks/<uuid:job_id>/trace/", AITraceView.as_view()),
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
    path("api/v1/projects/<uuid:project_id>/indexes/", IndexListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/search/", SearchView.as_view()),
    path("api/v1/health/live/", LiveView.as_view(), name="health-live"),
    path("api/v1/health/ready/", ReadyView.as_view(), name="health-ready"),
]
