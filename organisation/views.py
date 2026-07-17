from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from affectations.models import CentreImmersion
from sessions_app.models import SessionImmersion

from .models import (
    AffectationGroupe,
    AttributionLit,
    Dortoir,
    Groupe,
    Lit,
    RegleOrganisationCentre,
    Section,
)
from .permissions import (
    PermissionAffectationGroupe,
    PermissionAttributionLit,
    PermissionDortoir,
    PermissionGroupe,
    PermissionLit,
    PermissionRegleOrganisation,
    PermissionSection,
)
from .repository import (
    AffectationGroupeRepository,
    AttributionLitRepository,
    CandidatsOrganisationRepository,
    DortoirRepository,
    GroupeRepository,
    LitRepository,
    RegleOrganisationCentreRepository,
    SectionRepository,
)
from .serializers import (
    ActionOrganisationLotInputSerializer,
    AffectationGroupeManuelleInputSerializer,
    AffectationGroupeSerializer,
    AttributionLitManuelleInputSerializer,
    AttributionLitSerializer,
    DortoirInputSerializer,
    DortoirSerializer,
    DortoirUpdateSerializer,
    FiltreAffectationGroupeSerializer,
    FiltreAttributionLitSerializer,
    FiltreGroupeSerializer,
    FiltreHebergementSerializer,
    FiltreOrganisationSerializer,
    GenererStructuresInputSerializer,
    GroupeInputSerializer,
    GroupeSerializer,
    GroupeUpdateSerializer,
    LiberationLitInputSerializer,
    LitInputSerializer,
    LitSerializer,
    LitUpdateSerializer,
    ProgressionOrganisationSerializer,
    PropositionOrganisationLotInputSerializer,
    RegleOrganisationCentreInputSerializer,
    RegleOrganisationCentreSerializer,
    RegleOrganisationCentreUpdateSerializer,
    RejetOrganisationLotInputSerializer,
    SectionInputSerializer,
    SectionSerializer,
    SectionUpdateSerializer,
    TacheOrganisationLanceeSerializer,
)
from .service import (
    HebergementService,
    OrganisationCentreService,
    RegleOrganisationCentreService,
    ValidationOrganisationErreur,
)
from .tasks import (
    ProgressionOrganisationService,
    generer_sections_groupes_task,
    proposer_affectations_groupes_task,
    proposer_attributions_lits_task,
    rejeter_affectations_groupes_task,
    rejeter_attributions_lits_task,
    valider_affectations_groupes_task,
    valider_attributions_lits_task,
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
        (DjangoValidationError, ValidationOrganisationErreur),
    ):
        raise ValidationError(convertir_erreur(exception))
    if isinstance(exception, IntegrityError):
        raise ValidationError(
            {"detail": "Cette opération entre en conflit avec une donnée existante."}
        )
    raise exception


class OrganisationViewSetBase(viewsets.ModelViewSet):
    def lancer_tache(self, tache, *, operation, kwargs):
        resultat = tache.delay(**kwargs)
        donnees = {
            "task_id": str(resultat.id),
            "operation": operation,
            "message": "Traitement lancé en arrière-plan.",
        }
        return Response(
            TacheOrganisationLanceeSerializer(donnees).data,
            status=status.HTTP_202_ACCEPTED,
        )

    def reponse_progression(self, task_id):
        donnees = ProgressionOrganisationService.lire(task_id)
        return Response(ProgressionOrganisationSerializer(donnees).data)

    def verifier_objets_lot(self, request, queryset, ids):
        ids = list(dict.fromkeys(int(valeur) for valeur in ids))
        objets = list(queryset.filter(id__in=ids).order_by("id"))
        if len(objets) != len(ids):
            raise ValidationError(
                {"ids": "Un ou plusieurs éléments sont introuvables."}
            )
        for objet in objets:
            self.check_object_permissions(request, objet)
        return objets


class RegleOrganisationCentreViewSet(OrganisationViewSetBase):
    permission_classes = [PermissionRegleOrganisation]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return RegleOrganisationCentreRepository.actifs()

        filtre = FiltreOrganisationSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        return RegleOrganisationCentreRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return RegleOrganisationCentreInputSerializer
        if self.action in {"update", "partial_update"}:
            return RegleOrganisationCentreUpdateSerializer
        if self.action == "generer_structures":
            return GenererStructuresInputSerializer
        return RegleOrganisationCentreSerializer

    def create(self, request, *args, **kwargs):
        serializer = RegleOrganisationCentreInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)
        session_id = donnees.pop("session_id")
        centre_id = donnees.pop("centre_id")

        try:
            session = SessionImmersion.objects.get(
                id=session_id,
                deleted_at__isnull=True,
            )
            centre = CentreImmersion.objects.get(
                id=centre_id,
                deleted_at__isnull=True,
            )
            regle = RegleOrganisationCentreService.creer(
                session=session,
                centre=centre,
                acteur=request.user,
                **donnees,
            )
        except (
            SessionImmersion.DoesNotExist,
            CentreImmersion.DoesNotExist,
        ) as exception:
            raise ValidationError(
                {"detail": "La session ou le centre est introuvable."}
            ) from exception
        except (
            DjangoValidationError,
            ValidationOrganisationErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            RegleOrganisationCentreSerializer(regle).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        regle = self.get_object()
        serializer = RegleOrganisationCentreUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)

        try:
            regle = RegleOrganisationCentreService.modifier(
                regle.id,
                **serializer.validated_data,
            )
        except (
            DjangoValidationError,
            ValidationOrganisationErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(RegleOrganisationCentreSerializer(regle).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        regle = self.get_object()
        try:
            regle.supprimer_logiquement()
        except DjangoValidationError as exception:
            lever_erreur_service(exception)
        return Response(
            {"detail": "Règle d'organisation archivée."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="generer-structures")
    def generer_structures(self, request, pk=None):
        regle = self.get_object()
        serializer = GenererStructuresInputSerializer(
            data={
                "session_id": regle.session_id,
                "centre_id": regle.centre_id,
                "recreer": request.data.get("recreer", False),
            }
        )
        serializer.is_valid(raise_exception=True)
        return self.lancer_tache(
            generer_sections_groupes_task,
            operation="generer_sections_groupes",
            kwargs=serializer.validated_data,
        )

    @action(detail=True, methods=["post"], url_path="valider-organisation")
    def valider_organisation(self, request, pk=None):
        regle = self.get_object()
        try:
            regle = RegleOrganisationCentreService.valider_organisation(
                session_id=regle.session_id,
                centre_id=regle.centre_id,
                acteur=request.user,
            )
        except (
            DjangoValidationError,
            ValidationOrganisationErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)
        return Response(RegleOrganisationCentreSerializer(regle).data)

    @action(detail=True, methods=["post"], url_path="marquer-prete-publication")
    def marquer_prete_publication(self, request, pk=None):
        regle = self.get_object()
        try:
            regle = (
                RegleOrganisationCentreService.marquer_prete_publication(
                    session_id=regle.session_id,
                    centre_id=regle.centre_id,
                )
            )
        except (
            DjangoValidationError,
            ValidationOrganisationErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)
        return Response(RegleOrganisationCentreSerializer(regle).data)

    @action(detail=True, methods=["get"], url_path="synthese")
    def synthese(self, request, pk=None):
        regle = self.get_object()
        session_id = regle.session_id
        centre_id = regle.centre_id

        total_affectations = (
            CandidatsOrganisationRepository.compter_affectations_centre_actives(
                session_id=session_id,
                centre_id=centre_id,
            )
        )
        sections = SectionRepository.lister_par_session_centre(
            session_id,
            centre_id,
        ).count()
        groupes = GroupeRepository.lister_par_session_centre(
            session_id,
            centre_id,
        ).count()
        candidats_groupes = CandidatsOrganisationRepository.compter_candidats_groupes(
            session_id=session_id,
            centre_id=centre_id,
        )
        affectations_groupes_actives = (
            AffectationGroupeRepository.lister_actives()
            .filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
            )
            .count()
        )
        propositions_groupes = (
            AffectationGroupeRepository.lister_proposees()
            .filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
            )
            .count()
        )

        lits_utilisables = LitRepository.compter_exploitables_par_centre(centre_id)
        candidats_lits = (
            CandidatsOrganisationRepository.compter_candidats_lits(
                session_id=session_id,
                centre_id=centre_id,
            )
            if regle.hebergement_active
            else 0
        )
        attributions_lits_actives = (
            AttributionLitRepository.lister_actives()
            .filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
            )
            .count()
            if regle.hebergement_active
            else 0
        )
        propositions_lits = (
            AttributionLitRepository.lister_proposees()
            .filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
            )
            .count()
            if regle.hebergement_active
            else 0
        )

        structures_generees = sections > 0 and groupes > 0
        groupes_complets = (
            total_affectations > 0
            and affectations_groupes_actives == total_affectations
            and propositions_groupes == 0
            and candidats_groupes == 0
        )
        lits_complets = (
            not regle.hebergement_active
            or (
                attributions_lits_actives == total_affectations
                and propositions_lits == 0
                and candidats_lits == 0
            )
        )

        return Response(
            {
                "total_affectations_centre": total_affectations,
                "sections": sections,
                "groupes": groupes,
                "candidats_groupes": candidats_groupes,
                "affectations_groupes_actives": affectations_groupes_actives,
                "propositions_groupes": propositions_groupes,
                "hebergement_active": regle.hebergement_active,
                "lits_utilisables": lits_utilisables,
                "candidats_lits": candidats_lits,
                "attributions_lits_actives": attributions_lits_actives,
                "propositions_lits": propositions_lits,
                "actions": {
                    "peut_generer_structures": (
                        regle.repartition_sections_groupes_automatique
                        and total_affectations > 0
                        and not structures_generees
                    ),
                    "peut_valider_organisation": (
                        structures_generees and groupes_complets and lits_complets
                    ),
                    "peut_marquer_pret": regle.est_validee,
                },
            }
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"progression/(?P<task_id>[^/.]+)",
    )
    def progression(self, request, task_id=None):
        return self.reponse_progression(task_id)


class SectionViewSet(OrganisationViewSetBase):
    permission_classes = [PermissionSection]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return SectionRepository.actifs()
        filtre = FiltreOrganisationSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        return SectionRepository.filtrer(**filtre.validated_data)

    def get_serializer_class(self):
        if self.action == "create":
            return SectionInputSerializer
        if self.action in {"update", "partial_update"}:
            return SectionUpdateSerializer
        return SectionSerializer

    def create(self, request, *args, **kwargs):
        serializer = SectionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)
        try:
            section = SectionRepository.creer(**donnees)
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return Response(
            SectionSerializer(section).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        section = self.get_object()
        serializer = SectionUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        for champ, valeur in serializer.validated_data.items():
            setattr(section, champ, valeur)
        try:
            SectionRepository.sauvegarder(
                section,
                update_fields=[
                    *serializer.validated_data.keys(),
                    "updated_at",
                ],
            )
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return Response(SectionSerializer(section).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        section = self.get_object()
        try:
            section.supprimer_logiquement()
        except DjangoValidationError as exception:
            lever_erreur_service(exception)
        return Response({"detail": "Section archivée."})


class GroupeViewSet(OrganisationViewSetBase):
    permission_classes = [PermissionGroupe]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return GroupeRepository.actifs()
        filtre = FiltreGroupeSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        return GroupeRepository.filtrer(**filtre.validated_data)

    def get_serializer_class(self):
        if self.action == "create":
            return GroupeInputSerializer
        if self.action in {"update", "partial_update"}:
            return GroupeUpdateSerializer
        return GroupeSerializer

    def create(self, request, *args, **kwargs):
        serializer = GroupeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            groupe = GroupeRepository.creer(**serializer.validated_data)
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return Response(
            GroupeSerializer(groupe).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        groupe = self.get_object()
        serializer = GroupeUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        for champ, valeur in serializer.validated_data.items():
            setattr(groupe, champ, valeur)
        try:
            GroupeRepository.sauvegarder(
                groupe,
                update_fields=[
                    *serializer.validated_data.keys(),
                    "updated_at",
                ],
            )
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return Response(GroupeSerializer(groupe).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        groupe = self.get_object()
        try:
            groupe.supprimer_logiquement()
        except DjangoValidationError as exception:
            lever_erreur_service(exception)
        return Response({"detail": "Groupe archivé."})


class AffectationGroupeViewSet(OrganisationViewSetBase):
    permission_classes = [PermissionAffectationGroupe]
    http_method_names = [
        "get",
        "post",
        "delete",
        "head",
        "options",
    ]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return AffectationGroupeRepository.non_supprimees()
        filtre = FiltreAffectationGroupeSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return AffectationGroupeRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action in {"create", "affecter_manuellement"}:
            return AffectationGroupeManuelleInputSerializer
        if self.action == "proposer_lot":
            return PropositionOrganisationLotInputSerializer
        if self.action == "rejeter_lot":
            return RejetOrganisationLotInputSerializer
        if self.action == "valider_lot":
            return ActionOrganisationLotInputSerializer
        return AffectationGroupeSerializer

    def create(self, request, *args, **kwargs):
        serializer = AffectationGroupeManuelleInputSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        try:
            affectation = OrganisationCentreService.affecter_manuellement(
                **serializer.validated_data,
                acteur=request.user,
            )
        except (
            DjangoValidationError,
            ValidationOrganisationErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)
        return Response(
            AffectationGroupeSerializer(affectation).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="affecter-manuellement")
    def affecter_manuellement(self, request):
        return self.create(request)

    @action(detail=False, methods=["post"], url_path="proposer-lot")
    def proposer_lot(self, request):
        serializer = PropositionOrganisationLotInputSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        return self.lancer_tache(
            proposer_affectations_groupes_task,
            operation="proposer_affectations_groupes",
            kwargs={
                **serializer.validated_data,
                "acteur_id": request.user.id,
            },
        )

    @action(detail=False, methods=["post"], url_path="valider-lot")
    def valider_lot(self, request):
        serializer = ActionOrganisationLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        self.verifier_objets_lot(
            request,
            AffectationGroupeRepository.non_supprimees(),
            ids,
        )
        return self.lancer_tache(
            valider_affectations_groupes_task,
            operation="valider_affectations_groupes",
            kwargs={
                "affectation_ids": ids,
                "acteur_id": request.user.id,
                "observations": serializer.validated_data.get(
                    "observations",
                    "",
                ),
            },
        )

    @action(detail=False, methods=["post"], url_path="rejeter-lot")
    def rejeter_lot(self, request):
        serializer = RejetOrganisationLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        self.verifier_objets_lot(
            request,
            AffectationGroupeRepository.non_supprimees(),
            ids,
        )
        return self.lancer_tache(
            rejeter_affectations_groupes_task,
            operation="rejeter_affectations_groupes",
            kwargs={
                "affectation_ids": ids,
                "observations": serializer.validated_data["observations"],
            },
        )

    def destroy(self, request, *args, **kwargs):
        affectation = self.get_object()
        affectation.annuler(
            request.data.get(
                "observations",
                "Retrait manuel de l'organisation interne.",
            )
        )
        return Response({"detail": "Affectation groupe retirée."})

    @action(detail=True, methods=["post"], url_path="retirer")
    def retirer(self, request, pk=None):
        return self.destroy(request, pk=pk)

    @action(
        detail=False,
        methods=["get"],
        url_path=r"progression/(?P<task_id>[^/.]+)",
    )
    def progression(self, request, task_id=None):
        return self.reponse_progression(task_id)


class DortoirViewSet(OrganisationViewSetBase):
    permission_classes = [PermissionDortoir]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return DortoirRepository.actifs()
        filtre = FiltreHebergementSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        donnees = dict(filtre.validated_data)
        donnees.pop("dortoir_id", None)
        return DortoirRepository.filtrer(**donnees)

    def get_serializer_class(self):
        if self.action == "create":
            return DortoirInputSerializer
        if self.action in {"update", "partial_update"}:
            return DortoirUpdateSerializer
        return DortoirSerializer

    def create(self, request, *args, **kwargs):
        serializer = DortoirInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            dortoir = DortoirRepository.creer(**serializer.validated_data)
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return Response(
            DortoirSerializer(dortoir).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        dortoir = self.get_object()
        serializer = DortoirUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        for champ, valeur in serializer.validated_data.items():
            setattr(dortoir, champ, valeur)
        try:
            DortoirRepository.sauvegarder(
                dortoir,
                update_fields=[
                    *serializer.validated_data.keys(),
                    "updated_at",
                ],
            )
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return Response(DortoirSerializer(dortoir).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        dortoir = self.get_object()
        try:
            dortoir.supprimer_logiquement()
        except DjangoValidationError as exception:
            lever_erreur_service(exception)
        return Response({"detail": "Dortoir archivé."})

    @action(detail=True, methods=["post"], url_path="mettre-hors-service")
    def mettre_hors_service(self, request, pk=None):
        dortoir = self.get_object().mettre_hors_service()
        return Response(DortoirSerializer(dortoir).data)

    @action(detail=True, methods=["post"], url_path="reactiver")
    def reactiver(self, request, pk=None):
        try:
            dortoir = self.get_object().reactiver()
        except DjangoValidationError as exception:
            lever_erreur_service(exception)
        return Response(DortoirSerializer(dortoir).data)

    @action(detail=True, methods=["post"], url_path="generer-lits")
    def generer_lits(self, request, pk=None):
        dortoir = self.get_object()
        try:
            resultat = HebergementService.generer_lits_dortoir(
                dortoir_id=dortoir.id,
            )
        except (DjangoValidationError, ValidationOrganisationErreur, IntegrityError) as exception:
            lever_erreur_service(exception)
        return Response(resultat.en_dict(), status=status.HTTP_201_CREATED)


class LitViewSet(OrganisationViewSetBase):
    permission_classes = [PermissionLit]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return LitRepository.actifs()
        filtre = FiltreHebergementSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        return LitRepository.filtrer(**filtre.validated_data)

    def get_serializer_class(self):
        if self.action == "create":
            return LitInputSerializer
        if self.action in {"update", "partial_update"}:
            return LitUpdateSerializer
        return LitSerializer

    def create(self, request, *args, **kwargs):
        serializer = LitInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            lit = LitRepository.creer(**serializer.validated_data)
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return Response(
            LitSerializer(lit).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        lit = self.get_object()
        serializer = LitUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        for champ, valeur in serializer.validated_data.items():
            setattr(lit, champ, valeur)
        try:
            LitRepository.sauvegarder(
                lit,
                update_fields=[
                    *serializer.validated_data.keys(),
                    "updated_at",
                ],
            )
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return Response(LitSerializer(lit).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        lit = self.get_object()
        try:
            lit.supprimer_logiquement()
        except DjangoValidationError as exception:
            lever_erreur_service(exception)
        return Response({"detail": "Lit archivé."})

    @action(detail=True, methods=["post"], url_path="mettre-hors-service")
    def mettre_hors_service(self, request, pk=None):
        lit = self.get_object().mettre_hors_service()
        return Response(LitSerializer(lit).data)

    @action(detail=True, methods=["post"], url_path="reactiver")
    def reactiver(self, request, pk=None):
        try:
            lit = self.get_object().reactiver()
        except DjangoValidationError as exception:
            lever_erreur_service(exception)
        return Response(LitSerializer(lit).data)


class AttributionLitViewSet(OrganisationViewSetBase):
    permission_classes = [PermissionAttributionLit]
    http_method_names = [
        "get",
        "post",
        "delete",
        "head",
        "options",
    ]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return AttributionLitRepository.non_supprimees()
        filtre = FiltreAttributionLitSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return AttributionLitRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action in {"create", "attribuer_manuellement"}:
            return AttributionLitManuelleInputSerializer
        if self.action == "proposer_lot":
            return PropositionOrganisationLotInputSerializer
        if self.action == "rejeter_lot":
            return RejetOrganisationLotInputSerializer
        if self.action == "valider_lot":
            return ActionOrganisationLotInputSerializer
        if self.action == "liberer":
            return LiberationLitInputSerializer
        return AttributionLitSerializer

    def create(self, request, *args, **kwargs):
        serializer = AttributionLitManuelleInputSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        try:
            attribution = HebergementService.attribuer_manuellement(
                **serializer.validated_data,
                acteur=request.user,
            )
        except (
            DjangoValidationError,
            ValidationOrganisationErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)
        return Response(
            AttributionLitSerializer(attribution).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="attribuer-manuellement")
    def attribuer_manuellement(self, request):
        return self.create(request)

    @action(detail=False, methods=["post"], url_path="proposer-lot")
    def proposer_lot(self, request):
        serializer = PropositionOrganisationLotInputSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        return self.lancer_tache(
            proposer_attributions_lits_task,
            operation="proposer_attributions_lits",
            kwargs={
                **serializer.validated_data,
                "acteur_id": request.user.id,
            },
        )

    @action(detail=False, methods=["post"], url_path="valider-lot")
    def valider_lot(self, request):
        serializer = ActionOrganisationLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        self.verifier_objets_lot(
            request,
            AttributionLitRepository.non_supprimees(),
            ids,
        )
        return self.lancer_tache(
            valider_attributions_lits_task,
            operation="valider_attributions_lits",
            kwargs={
                "attribution_ids": ids,
                "acteur_id": request.user.id,
                "observations": serializer.validated_data.get(
                    "observations",
                    "",
                ),
            },
        )

    @action(detail=False, methods=["post"], url_path="rejeter-lot")
    def rejeter_lot(self, request):
        serializer = RejetOrganisationLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        self.verifier_objets_lot(
            request,
            AttributionLitRepository.non_supprimees(),
            ids,
        )
        return self.lancer_tache(
            rejeter_attributions_lits_task,
            operation="rejeter_attributions_lits",
            kwargs={
                "attribution_ids": ids,
                "observations": serializer.validated_data["observations"],
            },
        )

    def destroy(self, request, *args, **kwargs):
        attribution = self.get_object()
        attribution.liberer(
            request.data.get(
                "observations",
                "Libération manuelle du lit.",
            )
        )
        return Response({"detail": "Lit libéré."})

    @action(detail=True, methods=["post"], url_path="liberer")
    def liberer(self, request, pk=None):
        serializer = LiberationLitInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attribution = self.get_object()
        attribution.liberer(
            serializer.validated_data.get("observations", "")
        )
        return Response(AttributionLitSerializer(attribution).data)

    @action(
        detail=False,
        methods=["get"],
        url_path=r"progression/(?P<task_id>[^/.]+)",
    )
    def progression(self, request, task_id=None):
        return self.reponse_progression(task_id)
