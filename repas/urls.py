from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DemandeRavitaillementViewSet,
    LigneBesoinDenreeViewSet,
    OperationRepasViewSet,
    RepasJournalierViewSet,
    SuiviRepasViewSet,
)


app_name = "repas"

router = DefaultRouter()
router.register("demandes", DemandeRavitaillementViewSet, basename="demandes-ravitaillement")
router.register("denrees", LigneBesoinDenreeViewSet, basename="lignes-denrees")
router.register("repas", RepasJournalierViewSet, basename="repas-journaliers")
router.register("suivis", SuiviRepasViewSet, basename="suivis-repas")
router.register("operations", OperationRepasViewSet, basename="operations-repas")

urlpatterns = [path("", include(router.urls))]
