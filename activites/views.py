from __future__ import annotations

from django.core.exceptions import (
    ObjectDoesNotExist,
    ValidationError as DjangoValidationError,
)
from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from .models import (
    Evaluation,
    ModuleActivite,
    Note,
    Presence,
    Seance,
)
from .permissions import (
    PermissionEvaluation,
    PermissionModuleActivite,
    PermissionNote,
    PermissionOperationActivite,
    PermissionPresence,
    PermissionSeance,
)
from .repository import (
    EvaluationRepository,
    ModuleActiviteRepository,
    NoteRepository,
    PresenceRepository,
    SeanceRepository,
)
from .serializers import (
    AffecterFormateurSerializer,
    EvaluationCreateSerializer,
    EvaluationSerializer,
    EvaluationUpdateSerializer,
    FiltreEvaluationSerializer,
    FiltreModuleActiviteSerializer,
    FiltreNoteSerializer,
    FiltrePresenceSerializer,
    FiltreSeanceSerializer,
    MarquerNoteSerializer,
    ModuleActiviteCreateSerializer,
    ModuleActiviteSerializer,
    ModuleActiviteUpdateSerializer,
    MoyenneQuerySerializer,
    MoyenneSerializer,
    NoteCreateSerializer,
    NoteSerializer,
    NoteUpdateSerializer,
    PresenceCreateSerializer,
    PresenceSerializer,
    PresenceUpdateSerializer,
    ProgressionActiviteSerializer,
    ProgrammerEvaluationSerializer,
    RecalculIndicateursSerializer,
    ReporterSeanceSerializer,
    SaisieNotesMasseSerializer,
    SaisiePresencesMasseSerializer,
    SeanceCreateSerializer,
    SeanceIdSerializer,
    SeanceSerializer,
    SeanceUpdateSerializer,
    TacheActiviteLanceeSerializer,
    TauxPresenceQuerySerializer,
    TauxPresenceSerializer,
    ValidationFeuillesMasseSerializer,
    ValidationResultatsMasseSerializer,
)
from .service import (
    ActiviteService,
    EvaluationService,
    NoteService,
    PresenceService,
    SeanceService,
    ValidationActiviteErreur,
)
from .tasks import (
    ProgressionActivitesService,
    ouvrir_et_preparer_feuille_presence_task,
    recalculer_moyennes_task,
    recalculer_taux_presence_task,
    saisir_notes_masse_task,
    saisir_presences_masse_task,
    valider_feuilles_presence_masse_task,
    valider_resultats_masse_task,
)


def convertir_erreur(exception):
    if hasattr(exception, "message_dict"):
        return exception.message_dict
    if hasattr(exception, "messages"):
        return exception.messages
    return str(exception)


def lever_erreur_service(exception):
    if isinstance(
        exception,
        (DjangoValidationError, ValidationActiviteErreur),
    ):
        raise ValidationError(convertir_erreur(exception))

    if isinstance(exception, ObjectDoesNotExist):
        raise NotFound("La ressource demandée est introuvable.")

    if isinstance(exception, IntegrityError):
        raise ValidationError(
            {
                "detail": (
                    "Cette opération entre en conflit avec "
                    "une donnée existante."
                )
            }
        )
    raise exception


class ModuleActiviteViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionModuleActivite]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return ModuleActiviteRepository.non_supprimes()

        filtre = FiltreModuleActiviteSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return ModuleActiviteRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ModuleActiviteCreateSerializer
        if self.action in {"update", "partial_update"}:
            return ModuleActiviteUpdateSerializer
        return ModuleActiviteSerializer

    def create(self, request, *args, **kwargs):
        serializer = ModuleActiviteCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            module = ActiviteService.creer_activite(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            ModuleActiviteSerializer(module).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        module = self.get_object()
        serializer = ModuleActiviteUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)

        try:
            module = ActiviteService.modifier_activite(
                module.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(ModuleActiviteSerializer(module).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        module = self.get_object()

        try:
            ActiviteService.supprimer_activite_logiquement(
                module.id,
                acteur=request.user,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            {"detail": "Activité supprimée logiquement."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="desactiver")
    def desactiver(self, request, pk=None):
        module = self.get_object()

        try:
            module = ActiviteService.desactiver_activite(
                module.id,
                acteur=request.user,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(ModuleActiviteSerializer(module).data)

    @action(detail=True, methods=["post"], url_path="reactiver")
    def reactiver(self, request, pk=None):
        module = self.get_object()

        try:
            module = ActiviteService.reactiver_activite(
                module.id,
                acteur=request.user,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(ModuleActiviteSerializer(module).data)


class SeanceViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionSeance]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return SeanceRepository.non_supprimees()

        filtre = FiltreSeanceSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return SeanceRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return SeanceCreateSerializer
        if self.action in {"update", "partial_update"}:
            return SeanceUpdateSerializer
        if self.action == "reporter":
            return ReporterSeanceSerializer
        if self.action == "affecter_formateur":
            return AffecterFormateurSerializer
        return SeanceSerializer

    def create(self, request, *args, **kwargs):
        serializer = SeanceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            seance = SeanceService.planifier_seance(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            SeanceSerializer(seance).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        seance = self.get_object()
        serializer = SeanceUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)

        try:
            seance = SeanceService.modifier_seance(
                seance.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(SeanceSerializer(seance).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        seance = self.get_object()

        try:
            seance = SeanceService.annuler_seance(
                seance.id,
                acteur=request.user,
                observations=request.data.get("observations", ""),
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(SeanceSerializer(seance).data)

    @action(detail=True, methods=["post"], url_path="reporter")
    def reporter(self, request, pk=None):
        seance = self.get_object()
        serializer = ReporterSeanceSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            resultat = SeanceService.reporter_seance(
                seance.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            {
                "ancienne_seance": SeanceSerializer(
                    resultat["ancienne_seance"]
                ).data,
                "nouvelle_seance": SeanceSerializer(
                    resultat["nouvelle_seance"]
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="affecter-formateur",
    )
    def affecter_formateur(self, request, pk=None):
        seance = self.get_object()
        serializer = AffecterFormateurSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            seance = SeanceService.affecter_formateur(
                seance.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(SeanceSerializer(seance).data)


class PresenceViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionPresence]
    http_method_names = [
        "get",
        "post",
        "put",
        "patch",
        "head",
        "options",
    ]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return PresenceRepository.actives()

        filtre = FiltrePresenceSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return PresenceRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return PresenceCreateSerializer
        if self.action in {"update", "partial_update"}:
            return PresenceUpdateSerializer
        if self.action in {
            "ouvrir_feuille",
            "valider_feuille",
            "cloturer_feuille",
        }:
            return SeanceIdSerializer
        if self.action == "taux":
            return TauxPresenceQuerySerializer
        return PresenceSerializer

    def create(self, request, *args, **kwargs):
        serializer = PresenceCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            presence = PresenceService.saisir_presence(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            PresenceSerializer(presence).data,
            status=status.HTTP_200_OK,
        )

    def update(self, request, *args, **kwargs):
        presence = self.get_object()
        serializer = PresenceUpdateSerializer(
            data=request.data,
            partial=False,
        )
        serializer.is_valid(raise_exception=True)

        donnees = dict(serializer.validated_data)
        donnees.setdefault(
            "statut_presence",
            presence.statut_presence,
        )
        donnees.setdefault(
            "heure_arrivee",
            presence.heure_arrivee,
        )
        donnees.setdefault(
            "observations",
            presence.observations,
        )

        try:
            presence = PresenceService.modifier_presence(
                presence.id,
                acteur=request.user,
                **donnees,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(PresenceSerializer(presence).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    @action(
        detail=False,
        methods=["post"],
        url_path="ouvrir-feuille",
    )
    def ouvrir_feuille(self, request):
        serializer = SeanceIdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            seance = PresenceService.ouvrir_feuille_presence(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(SeanceSerializer(seance).data)

    @action(
        detail=False,
        methods=["post"],
        url_path="valider-feuille",
    )
    def valider_feuille(self, request):
        serializer = SeanceIdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            seance = PresenceService.valider_feuille_presence(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(SeanceSerializer(seance).data)

    @action(
        detail=False,
        methods=["post"],
        url_path="cloturer-feuille",
    )
    def cloturer_feuille(self, request):
        serializer = SeanceIdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            seance = PresenceService.cloturer_feuille_presence(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(SeanceSerializer(seance).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="taux",
    )
    def taux(self, request):
        serializer = TauxPresenceQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        try:
            resultat = PresenceService.calculer_taux_presence(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(TauxPresenceSerializer(resultat).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="statistiques",
    )
    def statistiques(self, request):
        serializer = SeanceIdSerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        statistiques = list(
            PresenceRepository.statistiques_seance(
                serializer.validated_data["seance_id"]
            )
        )
        return Response(statistiques)


class EvaluationViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionEvaluation]

    @action(detail=False, methods=["post"], url_path="programmer")
    def programmer(self, request):
        serializer = ProgrammerEvaluationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            evaluation = EvaluationService.programmer_evaluation(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)
        return Response(EvaluationSerializer(evaluation).data, status=status.HTTP_201_CREATED)

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return EvaluationRepository.non_supprimees()

        filtre = FiltreEvaluationSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return EvaluationRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return EvaluationCreateSerializer
        if self.action in {"update", "partial_update"}:
            return EvaluationUpdateSerializer
        return EvaluationSerializer

    def create(self, request, *args, **kwargs):
        serializer = EvaluationCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            evaluation = EvaluationService.creer_evaluation(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            EvaluationSerializer(evaluation).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        evaluation = self.get_object()
        serializer = EvaluationUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)

        try:
            evaluation = (
                EvaluationService.modifier_evaluation(
                    evaluation.id,
                    acteur=request.user,
                    **serializer.validated_data,
                )
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            EvaluationSerializer(evaluation).data
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        evaluation = self.get_object()

        try:
            evaluation = EvaluationService.annuler_evaluation(
                evaluation.id,
                acteur=request.user,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            EvaluationSerializer(evaluation).data
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="ouvrir-saisie",
    )
    def ouvrir_saisie(self, request, pk=None):
        evaluation = self.get_object()

        try:
            evaluation = EvaluationService.ouvrir_saisie_notes(
                evaluation.id,
                acteur=request.user,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            EvaluationSerializer(evaluation).data
        )

    @action(detail=True, methods=["post"], url_path="cloturer")
    def cloturer(self, request, pk=None):
        evaluation = self.get_object()

        try:
            evaluation = EvaluationService.cloturer_evaluation(
                evaluation.id,
                acteur=request.user,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            EvaluationSerializer(evaluation).data
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="valider-resultats",
    )
    def valider_resultats(self, request, pk=None):
        evaluation = self.get_object()

        try:
            evaluation = EvaluationService.valider_resultats(
                evaluation.id,
                acteur=request.user,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            EvaluationSerializer(evaluation).data
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="resultats",
    )
    def resultats(self, request, pk=None):
        evaluation = self.get_object()

        try:
            resultat = EvaluationService.consulter_resultats(
                evaluation.id
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            {
                "evaluation": EvaluationSerializer(
                    resultat["evaluation"]
                ).data,
                "notes": NoteSerializer(
                    resultat["notes"],
                    many=True,
                ).data,
                "statistiques": resultat["statistiques"],
            }
        )


class NoteViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionNote]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return NoteRepository.actives()

        filtre = FiltreNoteSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return NoteRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return NoteCreateSerializer
        if self.action in {"update", "partial_update"}:
            return NoteUpdateSerializer
        if self.action in {
            "marquer_absent",
            "marquer_dispense",
        }:
            return MarquerNoteSerializer
        if self.action == "moyenne":
            return MoyenneQuerySerializer
        return NoteSerializer

    def create(self, request, *args, **kwargs):
        serializer = NoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            note = NoteService.saisir_note(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(
            NoteSerializer(note).data,
            status=status.HTTP_200_OK,
        )

    def update(self, request, *args, **kwargs):
        note = self.get_object()
        serializer = NoteUpdateSerializer(
            data=request.data,
            partial=False,
        )
        serializer.is_valid(raise_exception=True)

        donnees = dict(serializer.validated_data)
        donnees.setdefault("statut_note", note.statut_note)
        donnees.setdefault("valeur", note.valeur)
        donnees.setdefault(
            "appreciation",
            note.appreciation,
        )
        donnees.setdefault(
            "observations",
            note.observations,
        )

        try:
            note = NoteService.modifier_note(
                note.id,
                acteur=request.user,
                **donnees,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(NoteSerializer(note).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        note = self.get_object()

        try:
            note = NoteService.annuler_note(
                note.id,
                acteur=request.user,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(NoteSerializer(note).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="marquer-absent",
    )
    def marquer_absent(self, request, pk=None):
        note = self.get_object()
        serializer = MarquerNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            note = NoteService.marquer_absent(
                note.id,
                acteur=request.user,
            )
            if serializer.validated_data.get("observations"):
                note.observations = serializer.validated_data[
                    "observations"
                ]
                note.save(
                    update_fields=["observations", "updated_at"]
                )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(NoteSerializer(note).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="marquer-dispense",
    )
    def marquer_dispense(self, request, pk=None):
        note = self.get_object()
        serializer = MarquerNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            note = NoteService.marquer_dispense(
                note.id,
                acteur=request.user,
            )
            if serializer.validated_data.get("observations"):
                note.observations = serializer.validated_data[
                    "observations"
                ]
                note.save(
                    update_fields=["observations", "updated_at"]
                )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(NoteSerializer(note).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="moyenne",
    )
    def moyenne(self, request):
        serializer = MoyenneQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        try:
            resultat = NoteService.calculer_moyenne(
                acteur=request.user,
                **serializer.validated_data,
            )
        except Exception as exception:
            lever_erreur_service(exception)

        return Response(MoyenneSerializer(resultat).data)


class OperationActiviteViewSet(viewsets.GenericViewSet):
    permission_classes = [PermissionOperationActivite]
    lookup_value_regex = r"[^/.]+"

    @staticmethod
    def _reponse_tache(tache, operation):
        donnees = {
            "task_id": tache.id,
            "operation": operation,
            "statut": ProgressionActivitesService.EN_ATTENTE,
            "message": "La tâche a été envoyée à Celery.",
        }
        return Response(
            TacheActiviteLanceeSerializer(donnees).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="preparer-feuille",
    )
    def preparer_feuille(self, request):
        serializer = SeanceIdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tache = ouvrir_et_preparer_feuille_presence_task.delay(
            acteur_id=request.user.id,
            **serializer.validated_data,
        )
        return self._reponse_tache(
            tache,
            "ouvrir_et_preparer_feuille_presence",
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="saisir-presences",
    )
    def saisir_presences(self, request):
        serializer = SaisiePresencesMasseSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        tache = saisir_presences_masse_task.delay(
            acteur_id=request.user.id,
            **serializer.validated_data,
        )
        return self._reponse_tache(
            tache,
            "saisir_presences_masse",
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="valider-feuilles",
    )
    def valider_feuilles(self, request):
        serializer = ValidationFeuillesMasseSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        tache = valider_feuilles_presence_masse_task.delay(
            acteur_id=request.user.id,
            **serializer.validated_data,
        )
        return self._reponse_tache(
            tache,
            "valider_feuilles_presence_masse",
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="saisir-notes",
    )
    def saisir_notes(self, request):
        serializer = SaisieNotesMasseSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        tache = saisir_notes_masse_task.delay(
            acteur_id=request.user.id,
            **serializer.validated_data,
        )
        return self._reponse_tache(
            tache,
            "saisir_notes_masse",
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="valider-resultats",
    )
    def valider_resultats(self, request):
        serializer = ValidationResultatsMasseSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        tache = valider_resultats_masse_task.delay(
            acteur_id=request.user.id,
            **serializer.validated_data,
        )
        return self._reponse_tache(
            tache,
            "valider_resultats_masse",
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="recalculer-taux",
    )
    def recalculer_taux(self, request):
        serializer = RecalculIndicateursSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        tache = recalculer_taux_presence_task.delay(
            acteur_id=request.user.id,
            **serializer.validated_data,
        )
        return self._reponse_tache(
            tache,
            "recalculer_taux_presence",
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="recalculer-moyennes",
    )
    def recalculer_moyennes(self, request):
        serializer = RecalculIndicateursSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        tache = recalculer_moyennes_task.delay(
            acteur_id=request.user.id,
            **serializer.validated_data,
        )
        return self._reponse_tache(
            tache,
            "recalculer_moyennes",
        )

    def retrieve(self, request, pk=None):
        progression = ProgressionActivitesService.lire(pk)
        return Response(
            ProgressionActiviteSerializer(progression).data
        )
