from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CorrespondanceColonneImportViewSet,
    ErreurImportViewSet,
    ImportOfficielViewSet,
    LigneImportViewSet,
)

app_name = "imports_app"

router = DefaultRouter()
router.register(
    r"imports-officiels",
    ImportOfficielViewSet,
    basename="import-officiel",
)
router.register(
    r"correspondances-colonnes",
    CorrespondanceColonneImportViewSet,
    basename="correspondance-colonne-import",
)
router.register(
    r"lignes",
    LigneImportViewSet,
    basename="ligne-import",
)
router.register(
    r"erreurs",
    ErreurImportViewSet,
    basename="erreur-import",
)

urlpatterns = [
    path("", include(router.urls)),
]
