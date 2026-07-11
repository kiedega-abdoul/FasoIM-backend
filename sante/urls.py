from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ImpactMedicalViewSet,
    RestrictionMedicaleViewSet,
    VisiteMedicaleViewSet,
)


app_name = "sante"

router = DefaultRouter()
router.register(
    "visites",
    VisiteMedicaleViewSet,
    basename="visites-medicales",
)
router.register(
    "restrictions",
    RestrictionMedicaleViewSet,
    basename="restrictions-medicales",
)
router.register(
    "impacts",
    ImpactMedicalViewSet,
    basename="impacts-medicaux",
)


urlpatterns = [
    path("", include(router.urls)),
]
