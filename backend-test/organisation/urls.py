from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AffectationGroupeViewSet,
    AttributionLitViewSet,
    DortoirViewSet,
    GroupeViewSet,
    LitViewSet,
    RegleOrganisationCentreViewSet,
    SectionViewSet,
)


app_name = "organisation"

router = DefaultRouter()
router.register(
    "regles-centres",
    RegleOrganisationCentreViewSet,
    basename="regles-centres",
)
router.register(
    "sections",
    SectionViewSet,
    basename="sections",
)
router.register(
    "groupes",
    GroupeViewSet,
    basename="groupes",
)
router.register(
    "affectations-groupes",
    AffectationGroupeViewSet,
    basename="affectations-groupes",
)
router.register(
    "dortoirs",
    DortoirViewSet,
    basename="dortoirs",
)
router.register(
    "lits",
    LitViewSet,
    basename="lits",
)
router.register(
    "attributions-lits",
    AttributionLitViewSet,
    basename="attributions-lits",
)


urlpatterns = [
    path("", include(router.urls)),
]
