from django.urls import path

from core.ai.views import AITaskView, AITraceView

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/ai-tasks/", AITaskView.as_view()),
    path("api/v1/projects/<uuid:project_id>/ai-tasks/<uuid:job_id>/trace/", AITraceView.as_view()),
]
