from django.urls import path

from core.expressions.views import (
    ExpressionTaskView,
    SuggestionDecisionView,
    SuggestionDetailView,
    SuggestionListView,
    SuggestionPreviewView,
)

urlpatterns = [
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
]
