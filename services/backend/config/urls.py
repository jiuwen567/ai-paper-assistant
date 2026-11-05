from django.urls import path

from core.accounts import LogoutView, SessionView
from core.ai_views import AITaskView, AITraceView
from core.cleanup_views import (
    CleanupCreateView,
    CleanupDetailView,
    CleanupListView,
    CleanupPreviewView,
)
from core.disclosure_views import (
    DisclosureHistoryView,
    DisclosureRevisionView,
    DisclosureView,
    UsageDetailView,
    UsageListView,
)
from core.evidence_links import EvidenceLinkHistoryView, EvidenceLinksView, EvidenceLinkView
from core.export_views import (
    ExportDetailView,
    ExportDownloadView,
    ExportPreviewView,
    ExportsView,
    ExportTemplatesView,
)
from core.expression_views import (
    ExpressionTaskView,
    SuggestionDecisionView,
    SuggestionDetailView,
    SuggestionListView,
    SuggestionPreviewView,
)
from core.feedback_views import (
    FeedbackCandidateDecisionView,
    FeedbackCandidatesView,
    FeedbackDetailView,
    FeedbackListView,
    FeedbackSplitView,
    FeedbackTaskCreateView,
    FeedbackTaskHistoryView,
    FeedbackTasksView,
    FeedbackTaskView,
    MentorReportsView,
)
from core.graph_views import GraphPathsView, GraphRebuildView
from core.impact_views import (
    ChangesView,
    ChangeView,
    ImpactModelView,
    ItemHistoryView,
    ItemsView,
    ItemView,
    RunsView,
    RunView,
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
    path("api/v1/projects/<uuid:project_id>/cleanup-preview/", CleanupPreviewView.as_view()),
    path("api/v1/projects/<uuid:project_id>/cleanup/", CleanupCreateView.as_view()),
    path("api/v1/cleanups/", CleanupListView.as_view()),
    path("api/v1/cleanups/<uuid:request_id>/", CleanupDetailView.as_view()),
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
    path("api/v1/projects/<uuid:project_id>/material-changes/", ChangesView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/material-changes/<uuid:change_id>/", ChangeView.as_view()
    ),
    path(
        "api/v1/projects/<uuid:project_id>/material-changes/<uuid:change_id>/runs/",
        RunsView.as_view(),
    ),
    path("api/v1/projects/<uuid:project_id>/impact-runs/<uuid:run_id>/", RunView.as_view()),
    path("api/v1/projects/<uuid:project_id>/impact-runs/<uuid:run_id>/items/", ItemsView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/impact-runs/<uuid:run_id>/model/",
        ImpactModelView.as_view(),
    ),
    path("api/v1/projects/<uuid:project_id>/impact-items/<uuid:item_id>/", ItemView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/impact-items/<uuid:item_id>/history/",
        ItemHistoryView.as_view(),
    ),
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
    path("api/v1/projects/<uuid:project_id>/feedback/", FeedbackListView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/feedback/<uuid:feedback_id>/",
        FeedbackDetailView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/feedback/<uuid:feedback_id>/split/",
        FeedbackSplitView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/feedback/<uuid:feedback_id>/candidates/",
        FeedbackCandidatesView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/feedback/<uuid:feedback_id>/tasks/",
        FeedbackTaskCreateView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/feedback-candidates/<uuid:candidate_id>/decision/",
        FeedbackCandidateDecisionView.as_view(),
    ),
    path("api/v1/projects/<uuid:project_id>/feedback-tasks/", FeedbackTasksView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/feedback-tasks/<uuid:task_id>/",
        FeedbackTaskView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/feedback-tasks/<uuid:task_id>/history/",
        FeedbackTaskHistoryView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:project_id>/feedback-tasks/<uuid:task_id>/mentor-reports/",
        MentorReportsView.as_view(),
    ),
    path("api/v1/projects/<uuid:project_id>/usage/", UsageListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/usage/<uuid:job_id>/", UsageDetailView.as_view()),
    path("api/v1/projects/<uuid:project_id>/disclosure/", DisclosureView.as_view()),
    path("api/v1/projects/<uuid:project_id>/disclosure/history/", DisclosureHistoryView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/disclosure/history/<int:number>/",
        DisclosureRevisionView.as_view(),
    ),
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
