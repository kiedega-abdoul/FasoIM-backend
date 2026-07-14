from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.dateparse import parse_date
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ParametreSession, SessionImmersion
from .permissions import PermissionParametreSession, PermissionSessionImmersion
from .repository import ParametreSessionRepository, SessionImmersionRepository
from .serializers import (
    AnnulationSessionSerializer,
    ParametreSessionCreateSerializer,
    ParametreSessionSerializer,
    SessionImmersionCreateSerializer,
    SessionImmersionSerializer,
    SessionPubliqueSerializer,
)
from .service import ParametreSessionService, SessionImmersionService


VALEURS_TRUE = {"true", "1", "oui", "yes", "vrai"}
VALEURS_FALSE = {"false", "0", "non", "no", "faux"}


def convertir_erreur_django(exc):
    """Convertit une ValidationError Django en erreur DRF exploitable par l'API."""
    if hasattr(exc, "message_dict"):
        return exc.message_dict

    if hasattr(exc, "messages"):
        return exc.messages

    return str(exc)


def lire_booleen(valeur, nom_champ):
    if valeur is None or valeur == "":
        return None

    valeur_normalisee = str(valeur).strip().lower()
    if valeur_normalisee in VALEURS_TRUE:
        return True

    if valeur_normalisee in VALEURS_FALSE:
        return False

    raise DRFValidationError({
        nom_champ: "Valeur booléenne invalide. Utiliser true/false, 1/0 ou oui/non."
    })


def lire_date(valeur, nom_champ):
    if not valeur:
        return None

    date_convertie = parse_date(valeur)
    if date_convertie is None:
        raise DRFValidationError({
            nom_champ: "Date invalide. Format attendu : AAAA-MM-JJ."
        })

    return date_convertie


def appliquer_filtre_liste(queryset, champ, valeur):
    """Accepte une valeur simple ou plusieurs valeurs séparées par des virgules."""
    if not valeur:
        return queryset

    valeurs = [element.strip() for element in str(valeur).split(",") if element.strip()]
    if not valeurs:
        return queryset

    return queryset.filter(**{f"{champ}__in": valeurs})


def appliquer_filtre_booleen(queryset, champ, valeur, nom_parametre):
    valeur_booleenne = lire_booleen(valeur, nom_parametre)
    if valeur_booleenne is None:
        return queryset

    return queryset.filter(**{champ: valeur_booleenne})


class SessionImmersionViewSet(viewsets.ModelViewSet):
    """API de gestion des sessions d'immersion."""

    permission_classes = [PermissionSessionImmersion]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "nom",
        "code",
        "description",
        "parametres__directives_generales",
        "parametres__consignes_generales",
    ]
    ordering_fields = [
        "annee",
        "numero_promotion",
        "date_debut",
        "date_fin",
        "nom",
        "code",
        "statut",
    ]
    ordering = ["-annee", "-numero_promotion", "-date_debut"]

    def get_queryset(self):
        queryset = SessionImmersionRepository.all_active()
        return self.appliquer_filtres(queryset)

    def get_serializer_class(self):
        if self.action == "create":
            return SessionImmersionCreateSerializer
        return SessionImmersionSerializer

    def appliquer_filtres(self, queryset):
        params = self.request.query_params

        queryset = appliquer_filtre_liste(queryset, "annee", params.get("annee"))
        queryset = appliquer_filtre_liste(
            queryset,
            "numero_promotion",
            params.get("numero_promotion"),
        )
        queryset = appliquer_filtre_liste(
            queryset,
            "type_session",
            params.get("type_session"),
        )
        queryset = appliquer_filtre_liste(
            queryset,
            "public_cible",
            params.get("public_cible"),
        )
        queryset = appliquer_filtre_liste(queryset, "statut", params.get("statut"))

        date_debut_min = lire_date(params.get("date_debut_min"), "date_debut_min")
        date_debut_max = lire_date(params.get("date_debut_max"), "date_debut_max")
        date_fin_min = lire_date(params.get("date_fin_min"), "date_fin_min")
        date_fin_max = lire_date(params.get("date_fin_max"), "date_fin_max")

        if date_debut_min:
            queryset = queryset.filter(date_debut__gte=date_debut_min)
        if date_debut_max:
            queryset = queryset.filter(date_debut__lte=date_debut_max)
        if date_fin_min:
            queryset = queryset.filter(date_fin__gte=date_fin_min)
        if date_fin_max:
            queryset = queryset.filter(date_fin__lte=date_fin_max)

        queryset = appliquer_filtre_liste(
            queryset,
            "parametres__mode_entree",
            params.get("mode_entree"),
        )

        filtres_booleens_parametres = {
            "hebergement_active": "parametres__hebergement_active",
            "repas_active": "parametres__repas_active",
            "visite_medicale_active": "parametres__visite_medicale_active",
            "evaluation_active": "parametres__evaluation_active",
            "attestation_active": "parametres__attestation_active",
            "consultation_publique_active": "parametres__consultation_publique_active",
        }

        for nom_parametre, champ in filtres_booleens_parametres.items():
            queryset = appliquer_filtre_booleen(
                queryset,
                champ,
                params.get(nom_parametre),
                nom_parametre,
            )

        return queryset

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

    @action(detail=True, methods=["get"], url_path="parametres")
    def parametres(self, request, pk=None):
        session = self.get_object()
        try:
            parametres = ParametreSessionRepository.get_by_session(session)
        except ParametreSession.DoesNotExist:
            return Response(
                {"detail": "Aucun paramètre actif trouvé pour cette session."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ParametreSessionSerializer(
            parametres,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

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

    @action(detail=True, methods=["post"], url_path="annuler")
    def annuler(self, request, pk=None):
        session = self.get_object()
        serializer = AnnulationSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session = SessionImmersionService.annuler_session(
                session, serializer.validated_data["motif"]
            )
        except DjangoValidationError as exc:
            raise DRFValidationError(convertir_erreur_django(exc))
        return Response(SessionImmersionSerializer(session).data)

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

    @action(detail=False, methods=["get"], url_path="historique")
    def historique(self, request):
        """
        Vue d'historique réservée à l'administration.

        Elle permet de retrouver les sessions actives, archivées, annulées ou
        supprimées logiquement, sans exposer les champs techniques dans l'API normale.
        """
        queryset = SessionImmersion.objects.all().select_related("parametres")
        queryset = self.appliquer_filtres(queryset)
        serializer = SessionImmersionSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class ParametreSessionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """API de consultation et modification des paramètres de session."""

    serializer_class = ParametreSessionSerializer
    permission_classes = [PermissionParametreSession]

    def get_serializer_class(self):
        if self.action == "create":
            return ParametreSessionCreateSerializer
        return ParametreSessionSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "session__nom",
        "session__code",
        "directives_generales",
        "consignes_generales",
    ]
    ordering_fields = [
        "session__annee",
        "session__numero_promotion",
        "session__date_debut",
        "session__nom",
        "mode_entree",
    ]
    ordering = ["-session__annee", "-session__numero_promotion"]

    def get_queryset(self):
        queryset = ParametreSessionRepository.all_active().filter(
            session__deleted_at__isnull=True,
        )
        return self.appliquer_filtres(queryset)

    def appliquer_filtres(self, queryset):
        params = self.request.query_params

        queryset = appliquer_filtre_liste(queryset, "session_id", params.get("session"))
        queryset = appliquer_filtre_liste(
            queryset,
            "session__annee",
            params.get("annee"),
        )
        queryset = appliquer_filtre_liste(
            queryset,
            "session__numero_promotion",
            params.get("numero_promotion"),
        )
        queryset = appliquer_filtre_liste(
            queryset,
            "session__type_session",
            params.get("type_session"),
        )
        queryset = appliquer_filtre_liste(
            queryset,
            "session__public_cible",
            params.get("public_cible"),
        )
        queryset = appliquer_filtre_liste(
            queryset,
            "session__statut",
            params.get("statut_session"),
        )
        queryset = appliquer_filtre_liste(queryset, "mode_entree", params.get("mode_entree"))

        filtres_booleens = {
            "hebergement_active": "hebergement_active",
            "repas_active": "repas_active",
            "visite_medicale_active": "visite_medicale_active",
            "evaluation_active": "evaluation_active",
            "attestation_active": "attestation_active",
            "consultation_publique_active": "consultation_publique_active",
        }

        for nom_parametre, champ in filtres_booleens.items():
            queryset = appliquer_filtre_booleen(
                queryset,
                champ,
                params.get(nom_parametre),
                nom_parametre,
            )

        return queryset

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

    @action(detail=False, methods=["get"], url_path="historique")
    def historique(self, request):
        """Historique des paramètres, réservé à l'administration."""
        queryset = ParametreSession.objects.all().select_related("session")
        queryset = self.appliquer_filtres(queryset)
        serializer = ParametreSessionSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class SessionsOuvertesPubliquesAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        queryset = SessionImmersionRepository.sessions_ouvertes_aux_inscriptions()
        serializer = SessionPubliqueSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
