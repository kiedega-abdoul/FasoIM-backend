from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import AlerteIncidentViewSet, OperationIncidentViewSet


app_name = "incidents"

operations_router = SimpleRouter()
operations_router.register(
    "operations",
    OperationIncidentViewSet,
    basename="operations-incidents",
)

incidents_router = SimpleRouter()
incidents_router.register(
    "",
    AlerteIncidentViewSet,
    basename="alertes-incidents",
)

urlpatterns = [
    path("", include(operations_router.urls)),
    path("", include(incidents_router.urls)),
]
