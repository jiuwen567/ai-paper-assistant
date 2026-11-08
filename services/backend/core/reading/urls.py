from django.urls import path

from core.reading.views import (
    ReadingDetailView,
    ReadingListView,
    ReadingSourceView,
    ReadingTaskView,
)

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/reading/", ReadingListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/reading/tasks/", ReadingTaskView.as_view()),
    path("api/v1/projects/<uuid:project_id>/reading/sources/", ReadingSourceView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/reading/<uuid:record_id>/", ReadingDetailView.as_view()
    ),
]
