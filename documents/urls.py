from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ConsultationArriveePubliqueView,
    ConsultationAttestationPubliqueView,
    DocumentGenereViewSet,
    EtatClotureSessionView,
    PublicationOfficielleViewSet,
    ResultatFinalViewSet,
    TelechargementAttestationPubliqueView,
    VerificationAttestationPubliqueView,
)

app_name = "documents"

router = DefaultRouter()
router.register("resultats", ResultatFinalViewSet, basename="resultat-final")
router.register("publications", PublicationOfficielleViewSet, basename="publication-officielle")
router.register("fichiers", DocumentGenereViewSet, basename="document-genere")

urlpatterns = [
    path("", include(router.urls)),
    path("cloture/sessions/<int:session_id>/", EtatClotureSessionView.as_view(), name="etat-cloture-session"),
    path("public/arrivee/", ConsultationArriveePubliqueView.as_view(), name="consultation-arrivee-publique"),
    path("public/attestations/consulter/", ConsultationAttestationPubliqueView.as_view(), name="consultation-attestation-publique"),
    path("public/attestations/verifier/", VerificationAttestationPubliqueView.as_view(), name="verification-attestation-publique"),
    path("public/attestations/<str:code>/telecharger/", TelechargementAttestationPubliqueView.as_view(), name="telechargement-attestation-publique"),
]
