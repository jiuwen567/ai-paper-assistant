from django.urls import include, path

urlpatterns = [
    path("", include("core.cleanup.urls")),
    path("", include("core.exports.urls")),
    path("", include("core.impacts.urls")),
    path("", include("core.graph.urls")),
    path("", include("core.accounts.urls")),
    path("", include("core.projects.urls")),
    path("", include("core.jobs.urls")),
    path("", include("core.feedback.urls")),
    path("", include("core.disclosures.urls")),
    path("", include("core.manuscripts.urls")),
    path("", include("core.ai.urls")),
    path("", include("core.expressions.urls")),
    path("", include("core.reviews.urls")),
    path("", include("core.reading.urls")),
    path("", include("core.materials.urls")),
    path("", include("core.library.urls")),
    path("", include("core.search.urls")),
    path("", include("core.system.urls")),
]
