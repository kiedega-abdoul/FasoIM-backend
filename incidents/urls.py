from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AlerteIncidentViewSet, OperationIncidentViewSet


app_name = "incidents"

router = DefaultRouter()
router.register("incidents", AlerteIncidentViewSet, basename="alertes-incidents")
router.register("operations", OperationIncidentViewSet, basename="operations-incidents")

urlpatterns = [path("", include(router.urls))]
