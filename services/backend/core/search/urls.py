from django.urls import path

from core.search.views import IndexListView, SearchView

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/indexes/", IndexListView.as_view()),
    path("api/v1/projects/<uuid:project_id>/search/", SearchView.as_view()),
]
