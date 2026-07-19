from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ImmergeConcoursViewSet,
    ImmergeExamenViewSet,
    ImmergeSelectionneViewSet,
    ImmergeViewSet,
    InscriptionVolontairePubliqueAPIView,
    InscriptionVolontaireViewSet,
    SuiviVolontairePublicAPIView,
)

app_name = "immerges"

router = DefaultRouter()
router.register(r"examens", ImmergeExamenViewSet, basename="immerge-examen")
router.register(r"concours", ImmergeConcoursViewSet, basename="immerge-concours")
router.register(
    r"selectionnes",
    ImmergeSelectionneViewSet,
    basename="immerge-selectionne",
)
router.register(
    r"volontaires",
    InscriptionVolontaireViewSet,
    basename="inscription-volontaire",
)
router.register(r"immerges", ImmergeViewSet, basename="immerge")

urlpatterns = [
    path(
        "public/volontaires/demandes/",
        InscriptionVolontairePubliqueAPIView.as_view(),
        name="inscription-volontaire-publique",
    ),
    path(
        "public/volontaires/suivi/",
        SuiviVolontairePublicAPIView.as_view(),
        name="suivi-volontaire-public",
    ),
    path("", include(router.urls)),
]