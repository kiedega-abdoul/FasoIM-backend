from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AffectationCentreViewSet,
    AffectationRegionaleViewSet,
    CentreImmersionViewSet,
    RegionImmersionViewSet,
)


app_name = "affectations"

router = DefaultRouter()
router.register(
    "regions",
    RegionImmersionViewSet,
    basename="regions-immersion",
)
router.register(
    "centres",
    CentreImmersionViewSet,
    basename="centres-immersion",
)
router.register(
    "affectations-regionales",
    AffectationRegionaleViewSet,
    basename="affectations-regionales",
)
router.register(
    "affectations-centres",
    AffectationCentreViewSet,
    basename="affectations-centres",
)


urlpatterns = [
    path("", include(router.urls)),
]
