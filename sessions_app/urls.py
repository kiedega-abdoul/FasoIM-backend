from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ParametreSessionViewSet, SessionImmersionViewSet


app_name = "sessions_app"

router = DefaultRouter()
router.register("sessions", SessionImmersionViewSet, basename="sessions")
router.register("parametres", ParametreSessionViewSet, basename="parametres")


urlpatterns = [
    path("", include(router.urls)),
]
