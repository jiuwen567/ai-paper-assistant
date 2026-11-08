from django.urls import path

from core.jobs.views import JobControlView, JobDetailView, JobListView

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/jobs/", JobListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/jobs/<uuid:job_id>/", JobDetailView.as_view()),
    path(
        "api/v1/projects/<uuid:project_id>/jobs/<uuid:job_id>/<str:action>/",
        JobControlView.as_view(),
    ),
]
