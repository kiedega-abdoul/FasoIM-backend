from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import filters, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from .models import SessionImmersion
from .repository import ParametreSessionRepository, SessionImmersionRepository
from .serializers import (
    ParametreSessionSerializer,
    SessionImmersionCreateSerializer,
    SessionImmersionSerializer,
)
from .service import ParametreSessionService, SessionImmersionService


def convertir_erreur_django(exc):
    """Convertit une ValidationError Django en ValidationError DRF exploitable par l'API."""
    if hasattr(exc, "message_dict"):
        return exc.message_dict

    if hasattr(exc, "messages"):
        return exc.messages

    return str(exc)


class SessionImmersionViewSet(viewsets.ModelViewSet):
    """API de gestion des sessions d'immersion."""

    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nom", "code", "description"]
    ordering_fields = [
        "annee",
        "numero_promotion",
        "date_debut",
        "date_fin",
        "nom",
        "code",
    ]
    ordering = ["-annee", "-numero_promotion", "-date_debut"]

    def get_queryset(self):
        queryset = SessionImmersionRepository.all_active()
        params = self.request.query_params

        annee = params.get("annee")
        numero_promotion = params.get("numero_promotion")
        type_session = params.get("type_session")
        public_cible = params.get("public_cible")
        statut = params.get("statut")

        if annee:
            queryset = queryset.filter(annee=annee)

        if numero_promotion:
            queryset = queryset.filter(numero_promotion=numero_promotion)

        if type_session:
            queryset = queryset.filter(type_session=type_session)

        if public_cible:
            queryset = queryset.filter(public_cible=public_cible)

        if statut:
            queryset = queryset.filter(statut=statut)

        return queryset

    def get_serializer_class(self):
        if self.action == "create":
            return SessionImmersionCreateSerializer
        return SessionImmersionSerializer

    def perform_create(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise DRFValidationError(convertir_erreur_django(exc))

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise DRFValidationError(convertir_erreur_django(exc))

    def perform_destroy(self, instance):
        try:
            SessionImmersionService.supprimer_logiquement(instance)
        except DjangoValidationError as exc:
            raise DRFValidationError(convertir_erreur_django(exc))

    def reponse_session(self, session):
        serializer = SessionImmersionSerializer(
            session,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def executer_action_session(self, operation):
        session = self.get_object()
        try:
            session = operation(session)
        except DjangoValidationError as exc:
            raise DRFValidationError(convertir_erreur_django(exc))
        return self.reponse_session(session)

    @action(detail=True, methods=["post"], url_path="ouvrir")
    def ouvrir(self, request, pk=None):
        return self.executer_action_session(SessionImmersionService.ouvrir_session)

    @action(detail=True, methods=["post"], url_path="mettre-en-preparation")
    def mettre_en_preparation(self, request, pk=None):
        return self.executer_action_session(
            SessionImmersionService.mettre_en_preparation
        )

    @action(detail=True, methods=["post"], url_path="demarrer")
    def demarrer(self, request, pk=None):
        return self.executer_action_session(SessionImmersionService.demarrer_session)

    @action(detail=True, methods=["post"], url_path="terminer")
    def terminer(self, request, pk=None):
        return self.executer_action_session(SessionImmersionService.terminer_session)

    @action(detail=True, methods=["post"], url_path="archiver")
    def archiver(self, request, pk=None):
        return self.executer_action_session(SessionImmersionService.archiver_session)

    @action(detail=False, methods=["get"], url_path="ouvertes-inscription")
    def ouvertes_inscription(self, request):
        queryset = SessionImmersionRepository.sessions_ouvertes_aux_inscriptions()
        serializer = SessionImmersionSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class ParametreSessionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """API de consultation et modification des paramètres de session."""

    serializer_class = ParametreSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "session__nom",
        "session__code",
        "directives_generales",
        "consignes_generales",
    ]
    ordering_fields = ["session__annee", "session__date_debut", "session__nom"]
    ordering = ["-session__annee", "-session__date_debut"]

    def get_queryset(self):
        queryset = ParametreSessionRepository.all_active().filter(
            session__deleted_at__isnull=True,
        )
        params = self.request.query_params

        session_id = params.get("session")
        mode_entree = params.get("mode_entree")
        hebergement_active = params.get("hebergement_active")
        repas_active = params.get("repas_active")
        visite_medicale_active = params.get("visite_medicale_active")
        attestation_active = params.get("attestation_active")

        if session_id:
            queryset = queryset.filter(session_id=session_id)

        if mode_entree:
            queryset = queryset.filter(mode_entree=mode_entree)

        filtres_booleens = {
            "hebergement_active": hebergement_active,
            "repas_active": repas_active,
            "visite_medicale_active": visite_medicale_active,
            "attestation_active": attestation_active,
        }

        for champ, valeur in filtres_booleens.items():
            if valeur in ["true", "True", "1"]:
                queryset = queryset.filter(**{champ: True})
            elif valeur in ["false", "False", "0"]:
                queryset = queryset.filter(**{champ: False})

        return queryset

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise DRFValidationError(convertir_erreur_django(exc))

    @action(detail=True, methods=["post"], url_path="supprimer-logiquement")
    def supprimer_logiquement(self, request, pk=None):
        parametres = self.get_object()
        try:
            ParametreSessionService.supprimer_logiquement(parametres)
        except DjangoValidationError as exc:
            raise DRFValidationError(convertir_erreur_django(exc))

        return Response(status=status.HTTP_204_NO_CONTENT)
