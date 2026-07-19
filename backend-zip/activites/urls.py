from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EvaluationViewSet,
    ModuleActiviteViewSet,
    NoteViewSet,
    OperationActiviteViewSet,
    PresenceViewSet,
    SeanceViewSet,
)


app_name = "activites"

router = DefaultRouter()
router.register(
    "activites",
    ModuleActiviteViewSet,
    basename="activites",
)
router.register(
    "seances",
    SeanceViewSet,
    basename="seances",
)
router.register(
    "presences",
    PresenceViewSet,
    basename="presences",
)
router.register(
    "evaluations",
    EvaluationViewSet,
    basename="evaluations",
)
router.register(
    "notes",
    NoteViewSet,
    basename="notes",
)
router.register(
    "operations",
    OperationActiviteViewSet,
    basename="operations-activites",
)


urlpatterns = [
    path("", include(router.urls)),
]
