from django.urls import path

from core.feedback.views import (
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

urlpatterns = [
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
]
