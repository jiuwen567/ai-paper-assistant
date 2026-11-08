from django.urls import path

from core.impacts.views import (
    ChangesView,
    ChangeView,
    ImpactModelView,
    ItemHistoryView,
    ItemsView,
    ItemView,
    RunsView,
    RunView,
)

urlpatterns = [
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
]
