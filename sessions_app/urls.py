from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ParametreSessionViewSet,
    SessionImmersionViewSet,
    SessionsOuvertesPubliquesAPIView,
)

app_name = "sessions_app"

router = DefaultRouter()
router.register("sessions", SessionImmersionViewSet, basename="sessions")
router.register("parametres", ParametreSessionViewSet, basename="parametres")

urlpatterns = [
    path(
        "public/ouvertes-inscription/",
        SessionsOuvertesPubliquesAPIView.as_view(),
        name="sessions-ouvertes-publiques",
    ),
    path("", include(router.urls)),
]