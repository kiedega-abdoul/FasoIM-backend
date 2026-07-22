from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ParametreSessionViewSet,
    SessionImmersionViewSet,
    SessionsOuvertesPubliquesAPIView,
    SessionsConsultablesArriveeAPIView,
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
    path(
        "public/consultables-arrivee/",
        SessionsConsultablesArriveeAPIView.as_view(),
        name="sessions-consultables-arrivee",
    ),
    path("", include(router.urls)),
]