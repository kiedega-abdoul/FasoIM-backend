from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from .permissions import (
    PermissionDemandeRavitaillement,
    PermissionLigneDenree,
    PermissionOperationRepas,
    PermissionRepasJournalier,
    PermissionSuiviRepas,
)
from .repository import (
    DemandeRavitaillementRepository,
    LigneBesoinDenreeRepository,
    RepasJournalierRepository,
    SuiviRepasRepository,
)
from .serializers import (
    AnnulationRepasSerializer,
    ConsolidationDenreesSerializer,
    DemandeRavitaillementCreateSerializer,
    DemandeRavitaillementSerializer,
    DemandeRavitaillementUpdateSerializer,
    FiltreDemandeSerializer,
    FiltreLigneDenreeSerializer,
    FiltreRepasSerializer,
    FiltreSuiviRepasSerializer,
    LigneBesoinDenreeInputSerializer,
    LigneBesoinDenreeSerializer,
    LigneBesoinDenreeUpdateSerializer,
    LancementOperationRepasSerializer,
    PreparationReelleSerializer,
    ProgressionRepasSerializer,
    RapportRepasSerializer,
    ReceptionDenreeSerializer,
    RepasCreateSerializer,
    RepasJournalierSerializer,
    RepasUpdateSerializer,
    SaisieComptageSerializer,
    ServiceMedicalSerializer,
    SuiviRepasSerializer,
    TacheRepasLanceeSerializer,
    ValidationDemandeSerializer,
)
from .service import RavitaillementService, RepasService, ValidationRepasErreur
from .tasks import (
    ProgressionRepasService,
    actualiser_besoins_sante_repas_task,
    cloturer_repas_task,
    consolider_besoins_denrees_task,
    generer_rapport_repas_task,
    preparer_suivis_repas_task,
)


def _convertir_erreur(exception):
    if hasattr(exception, "message_dict"):
        return exception.message_dict
    if hasattr(exception, "messages"):
        return exception.messages
    return str(exception)


def _lever_erreur(exception):
    if isinstance(exception, (DjangoValidationError, ValidationRepasErreur)):
        raise ValidationError(_convertir_erreur(exception))
    if isinstance(exception, ObjectDoesNotExist):
        raise NotFound("La ressource demandée est introuvable.")
    if isinstance(exception, IntegrityError):
        raise ValidationError(
            {"detail": "Cette opération entre en conflit avec une donnée existante."}
        )
    raise exception


def _reponse_tache(resultat, operation):
    donnees = {
        "task_id": str(resultat.id),
        "operation": operation,
        "statut": ProgressionRepasService.EN_ATTENTE,
        "progression": 0,
        "message": "Traitement placé dans la file Celery.",
    }
    return Response(
        TacheRepasLanceeSerializer(donnees).data,
        status=status.HTTP_202_ACCEPTED,
    )


class DemandeRavitaillementViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionDemandeRavitaillement]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return DemandeRavitaillementRepository.non_supprimees()
        filtre = FiltreDemandeSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        return DemandeRavitaillementRepository.filtrer(**filtre.validated_data)

    def get_serializer_class(self):
        if self.action == "create":
            return DemandeRavitaillementCreateSerializer
        if self.action in {"update", "partial_update"}:
            return DemandeRavitaillementUpdateSerializer
        if self.action == "ajouter_denree":
            return LigneBesoinDenreeInputSerializer
        if self.action == "valider":
            return ValidationDemandeSerializer
        return DemandeRavitaillementSerializer

    def create(self, request, *args, **kwargs):
        serializer = DemandeRavitaillementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            demande = RavitaillementService.creer_demande(
                acteur=request.user, **serializer.validated_data
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(
            DemandeRavitaillementSerializer(demande).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        serializer = DemandeRavitaillementUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            demande = RavitaillementService.modifier_demande(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(DemandeRavitaillementSerializer(demande).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        demande = self.get_object()
        if not demande.est_modifiable:
            raise ValidationError("Seule une demande en brouillon peut être supprimée.")
        demande.supprimer_logiquement()
        return Response({"detail": "Demande supprimée logiquement."})

    @action(detail=True, methods=["post"], url_path="denrees")
    def ajouter_denree(self, request, pk=None):
        serializer = LigneBesoinDenreeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ligne = RavitaillementService.ajouter_denree(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(
            LigneBesoinDenreeSerializer(ligne).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def soumettre(self, request, pk=None):
        try:
            demande = RavitaillementService.soumettre(
                self.get_object().id, acteur=request.user
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(DemandeRavitaillementSerializer(demande).data)

    @action(detail=True, methods=["post"])
    def valider(self, request, pk=None):
        serializer = ValidationDemandeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            demande = RavitaillementService.valider(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(DemandeRavitaillementSerializer(demande).data)


class LigneBesoinDenreeViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionLigneDenree]
    http_method_names = ["get", "put", "patch", "delete", "post", "head", "options"]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return LigneBesoinDenreeRepository.non_supprimees()
        filtre = FiltreLigneDenreeSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        return LigneBesoinDenreeRepository.filtrer(**filtre.validated_data)

    def get_serializer_class(self):
        if self.action in {"update", "partial_update"}:
            return LigneBesoinDenreeUpdateSerializer
        if self.action == "reception":
            return ReceptionDenreeSerializer
        return LigneBesoinDenreeSerializer

    def update(self, request, *args, **kwargs):
        serializer = LigneBesoinDenreeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ligne = RavitaillementService.modifier_denree(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(LigneBesoinDenreeSerializer(ligne).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        try:
            RavitaillementService.supprimer_denree(
                self.get_object().id, acteur=request.user
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response({"detail": "Ligne supprimée logiquement."})

    @action(detail=True, methods=["post"])
    def reception(self, request, pk=None):
        serializer = ReceptionDenreeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ligne = RavitaillementService.enregistrer_reception(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(LigneBesoinDenreeSerializer(ligne).data)


class RepasJournalierViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionRepasJournalier]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return RepasJournalierRepository.non_supprimes()
        filtre = FiltreRepasSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        return RepasJournalierRepository.filtrer(**filtre.validated_data)

    def get_serializer_class(self):
        if self.action == "create":
            return RepasCreateSerializer
        if self.action in {"update", "partial_update"}:
            return RepasUpdateSerializer
        if self.action == "terminer_preparation":
            return PreparationReelleSerializer
        if self.action == "annuler":
            return AnnulationRepasSerializer
        return RepasJournalierSerializer

    def create(self, request, *args, **kwargs):
        serializer = RepasCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            repas = RepasService.creer(
                acteur=request.user, **serializer.validated_data
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(
            RepasJournalierSerializer(repas).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        serializer = RepasUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            repas = RepasService.modifier(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(RepasJournalierSerializer(repas).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def _action_simple(self, request, methode):
        try:
            repas = methode(self.get_object().id, acteur=request.user)
        except Exception as exception:
            _lever_erreur(exception)
        return Response(RepasJournalierSerializer(repas).data)

    @action(detail=True, methods=["post"], url_path="actualiser-sante")
    def actualiser_sante(self, request, pk=None):
        return self._action_simple(request, RepasService.actualiser_besoins_sante)

    @action(detail=True, methods=["post"])
    def planifier(self, request, pk=None):
        return self._action_simple(request, RepasService.planifier)

    @action(detail=True, methods=["post"], url_path="valider-planification")
    def valider_planification(self, request, pk=None):
        return self._action_simple(request, RepasService.valider_planification)

    @action(detail=True, methods=["post"], url_path="demarrer-preparation")
    def demarrer_preparation(self, request, pk=None):
        return self._action_simple(request, RepasService.demarrer_preparation)

    @action(detail=True, methods=["post"], url_path="terminer-preparation")
    def terminer_preparation(self, request, pk=None):
        serializer = PreparationReelleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            repas = RepasService.terminer_preparation(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(RepasJournalierSerializer(repas).data)

    @action(detail=True, methods=["post"], url_path="ouvrir-distribution")
    def ouvrir_distribution(self, request, pk=None):
        return self._action_simple(request, RepasService.ouvrir_distribution)

    @action(detail=True, methods=["post"])
    def annuler(self, request, pk=None):
        serializer = AnnulationRepasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            repas = RepasService.annuler(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(RepasJournalierSerializer(repas).data)

    @action(detail=False, methods=["get"])
    def statistiques(self, request):
        filtre = FiltreRepasSerializer(data=request.query_params)
        filtre.is_valid(raise_exception=True)
        try:
            resultat = RepasService.statistiques(
                acteur=request.user, **filtre.validated_data
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(resultat)


class SuiviRepasViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [PermissionSuiviRepas]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return SuiviRepasRepository.non_supprimes()
        filtre = FiltreSuiviRepasSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        return SuiviRepasRepository.filtrer(**filtre.validated_data)

    def get_serializer_class(self):
        if self.action == "saisir_comptage":
            return SaisieComptageSerializer
        if self.action == "marquer_service":
            return ServiceMedicalSerializer
        return SuiviRepasSerializer

    @action(detail=True, methods=["post"], url_path="saisir-comptage")
    def saisir_comptage(self, request, pk=None):
        serializer = SaisieComptageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            suivi = RepasService.saisir_comptage(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(SuiviRepasSerializer(suivi).data)

    @action(detail=True, methods=["post"], url_path="marquer-service")
    def marquer_service(self, request, pk=None):
        serializer = ServiceMedicalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            suivi = RepasService.marquer_service_medical(
                self.get_object().id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            _lever_erreur(exception)
        return Response(SuiviRepasSerializer(suivi).data)


class OperationRepasViewSet(viewsets.ViewSet):
    permission_classes = [PermissionOperationRepas]

    def retrieve(self, request, pk=None):
        return Response(
            ProgressionRepasSerializer(
                ProgressionRepasService.lire(pk)
            ).data
        )

    @action(detail=False, methods=["post"], url_path="preparer-suivis")
    def preparer_suivis(self, request):
        serializer = LancementOperationRepasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = preparer_suivis_repas_task.delay(
            repas_id=serializer.validated_data["repas_id"],
            acteur_id=request.user.id,
        )
        return _reponse_tache(resultat, "preparation_suivis")

    @action(detail=False, methods=["post"], url_path="actualiser-sante")
    def actualiser_sante(self, request):
        serializer = LancementOperationRepasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = actualiser_besoins_sante_repas_task.delay(
            repas_id=serializer.validated_data["repas_id"],
            acteur_id=request.user.id,
        )
        return _reponse_tache(resultat, "actualisation_sante")

    @action(detail=False, methods=["post"])
    def cloturer(self, request):
        serializer = LancementOperationRepasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = cloturer_repas_task.delay(
            repas_id=serializer.validated_data["repas_id"],
            acteur_id=request.user.id,
        )
        return _reponse_tache(resultat, "cloture")

    @action(detail=False, methods=["post"])
    def rapport(self, request):
        serializer = RapportRepasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        filtres = {
            cle: (valeur.isoformat() if hasattr(valeur, "isoformat") else valeur)
            for cle, valeur in serializer.validated_data.items()
        }
        resultat = generer_rapport_repas_task.delay(
            acteur_id=request.user.id,
            filtres=filtres,
        )
        return _reponse_tache(resultat, "rapport")

    @action(detail=False, methods=["post"], url_path="consolider-denrees")
    def consolider_denrees(self, request):
        serializer = ConsolidationDenreesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = consolider_besoins_denrees_task.delay(
            acteur_id=request.user.id,
            **serializer.validated_data,
        )
        return _reponse_tache(resultat, "consolidation_denrees")
