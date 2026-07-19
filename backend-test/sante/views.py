from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import RestrictionMedicale, VisiteMedicale
from .permissions import (
    PermissionImpactMedical,
    PermissionRestrictionMedicale,
    PermissionVisiteMedicale,
)
from .repository import (
    CandidatVisiteMedicaleRepository,
    RestrictionMedicaleRepository,
    VisiteMedicaleRepository,
)
from .serializers import (
    AffectationCentreSanteSerializer,
    BrouillonVisiteMedicaleInputSerializer,
    CandidatsVisiteMedicaleQuerySerializer,
    ContreVisiteMedicaleInputSerializer,
    DecisionMedicaleSerializer,
    EnregistrementVisiteMedicaleInputSerializer,
    FiltreRestrictionMedicaleSerializer,
    FiltreVisiteMedicaleSerializer,
    ImpactMedicalQuerySerializer,
    LeverRestrictionInputSerializer,
    ProchaineVisiteQuerySerializer,
    RestrictionMedicaleCreateSerializer,
    RestrictionMedicaleSerializer,
    RestrictionMedicaleUpdateSerializer,
    ResultatApplicationMedicaleSerializer,
    ResultatEnregistrementVisiteSerializer,
    StatistiqueVisiteMedicaleSerializer,
    StatistiquesVisitesQuerySerializer,
    VisiteMedicaleSerializer,
)
from .service import (
    ImpactMedicalService,
    RestrictionMedicaleService,
    ValidationSanteErreur,
    VisiteMedicaleService,
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
        (DjangoValidationError, ValidationSanteErreur),
    ):
        raise ValidationError(convertir_erreur(exception))
    if isinstance(exception, IntegrityError):
        raise ValidationError(
            {
                "detail": (
                    "Cette opération entre en conflit avec "
                    "une donnée médicale existante."
                )
            }
        )
    raise exception


class VisiteMedicaleViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionVisiteMedicale]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = [
        "get",
        "post",
        "delete",
        "head",
        "options",
    ]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return VisiteMedicaleRepository.non_supprimees()

        filtre = FiltreVisiteMedicaleSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return VisiteMedicaleRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return EnregistrementVisiteMedicaleInputSerializer
        if self.action == "brouillon":
            return BrouillonVisiteMedicaleInputSerializer
        if self.action == "contre_visite":
            return ContreVisiteMedicaleInputSerializer
        if self.action == "candidats":
            return CandidatsVisiteMedicaleQuerySerializer
        if self.action == "prochaine":
            return ProchaineVisiteQuerySerializer
        if self.action == "statistiques":
            return StatistiquesVisitesQuerySerializer
        return VisiteMedicaleSerializer

    def create(self, request, *args, **kwargs):
        serializer = EnregistrementVisiteMedicaleInputSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)
        restrictions = donnees.pop("restrictions", [])
        affectation_centre_id = donnees.pop(
            "affectation_centre_id"
        )

        try:
            resultat = (
                VisiteMedicaleService.enregistrer_et_appliquer(
                    affectation_centre_id=affectation_centre_id,
                    acteur=request.user,
                    restrictions=restrictions,
                    **donnees,
                )
            )
        except (
            DjangoValidationError,
            ValidationSanteErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            ResultatEnregistrementVisiteSerializer(
                resultat.en_dict()
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="brouillon")
    def brouillon(self, request):
        serializer = BrouillonVisiteMedicaleInputSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)
        restrictions = donnees.pop("restrictions", None)
        affectation_centre_id = donnees.pop(
            "affectation_centre_id"
        )

        try:
            visite = (
                VisiteMedicaleService.creer_ou_modifier_brouillon(
                    affectation_centre_id=affectation_centre_id,
                    acteur=request.user,
                    restrictions=restrictions,
                    **donnees,
                )
            )
        except (
            DjangoValidationError,
            ValidationSanteErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        visite = VisiteMedicaleRepository.get_by_id(visite.id)
        return Response(
            VisiteMedicaleSerializer(visite).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="contre-visite",
    )
    def contre_visite(self, request):
        serializer = ContreVisiteMedicaleInputSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)
        restrictions = donnees.pop("restrictions", [])
        affectation_centre_id = donnees.pop(
            "affectation_centre_id"
        )

        try:
            resultat = (
                VisiteMedicaleService.corriger_par_contre_visite(
                    affectation_centre_id=affectation_centre_id,
                    acteur=request.user,
                    restrictions=restrictions,
                    **donnees,
                )
            )
        except (
            DjangoValidationError,
            ValidationSanteErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            ResultatEnregistrementVisiteSerializer(
                resultat.en_dict()
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="reappliquer")
    def reappliquer(self, request, pk=None):
        visite = self.get_object()

        try:
            resultat = VisiteMedicaleService.reappliquer_resultat(
                visite.id
            )
        except (
            DjangoValidationError,
            ValidationSanteErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            ResultatApplicationMedicaleSerializer(
                resultat.en_dict()
            ).data
        )

    def destroy(self, request, *args, **kwargs):
        visite = self.get_object()

        try:
            VisiteMedicaleService.annuler_visite(visite.id)
        except (
            DjangoValidationError,
            ValidationSanteErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            {"detail": "Visite médicale annulée."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="annuler")
    def annuler(self, request, pk=None):
        return self.destroy(request, pk=pk)

    @action(detail=False, methods=["get"], url_path="candidats")
    def candidats(self, request):
        serializer = CandidatsVisiteMedicaleQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        queryset = CandidatVisiteMedicaleRepository.filtrer(
            **serializer.validated_data
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            donnees = AffectationCentreSanteSerializer(
                page,
                many=True,
            ).data
            return self.get_paginated_response(donnees)

        return Response(
            AffectationCentreSanteSerializer(
                queryset,
                many=True,
            ).data
        )

    @action(detail=False, methods=["get"], url_path="prochaine")
    def prochaine(self, request):
        serializer = ProchaineVisiteQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        affectation = VisiteMedicaleService.prochaine_affectation(
            **serializer.validated_data
        )
        if not affectation:
            return Response(
                {
                    "detail": (
                        "Aucun immergé ne reste à visiter "
                        "dans ce centre."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            AffectationCentreSanteSerializer(affectation).data
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="statistiques",
    )
    def statistiques(self, request):
        serializer = StatistiquesVisitesQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        statistiques = list(
            VisiteMedicaleRepository.statistiques(
                **serializer.validated_data
            )
        )
        return Response(
            StatistiqueVisiteMedicaleSerializer(
                statistiques,
                many=True,
            ).data
        )


class RestrictionMedicaleViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionRestrictionMedicale]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return RestrictionMedicaleRepository.non_supprimees()

        filtre = FiltreRestrictionMedicaleSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return RestrictionMedicaleRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return RestrictionMedicaleCreateSerializer
        if self.action in {"update", "partial_update"}:
            return RestrictionMedicaleUpdateSerializer
        if self.action == "lever":
            return LeverRestrictionInputSerializer
        return RestrictionMedicaleSerializer

    def create(self, request, *args, **kwargs):
        serializer = RestrictionMedicaleCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)
        visite_medicale_id = donnees.pop("visite_medicale_id")

        try:
            visite = VisiteMedicaleRepository.get_by_id(
                visite_medicale_id
            )
            restriction = RestrictionMedicaleService.creer(
                visite_medicale=visite,
                acteur=request.user,
                **donnees,
            )
        except VisiteMedicale.DoesNotExist as exception:
            raise NotFound(
                "La visite médicale est introuvable."
            ) from exception
        except (
            DjangoValidationError,
            ValidationSanteErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            RestrictionMedicaleSerializer(restriction).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        restriction = self.get_object()
        serializer = RestrictionMedicaleUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)

        try:
            restriction = RestrictionMedicaleService.modifier(
                restriction.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (
            DjangoValidationError,
            ValidationSanteErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            RestrictionMedicaleSerializer(restriction).data
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        restriction = self.get_object()
        try:
            restriction.supprimer_logiquement()
        except DjangoValidationError as exception:
            lever_erreur_service(exception)

        return Response(
            {"detail": "Restriction médicale annulée."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="lever")
    def lever(self, request, pk=None):
        restriction = self.get_object()
        serializer = LeverRestrictionInputSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            restriction = RestrictionMedicaleService.lever(
                restriction.id,
                motif=serializer.validated_data.get(
                    "motif",
                    "",
                ),
                acteur=request.user,
            )
        except (
            DjangoValidationError,
            ValidationSanteErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            RestrictionMedicaleSerializer(restriction).data
        )


class ImpactMedicalViewSet(viewsets.GenericViewSet):
    permission_classes = [PermissionImpactMedical]
    lookup_value_regex = r"\d+"

    def retrieve(self, request, pk=None):
        serializer = ImpactMedicalQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        affectation_centre_id = int(pk)
        module = serializer.validated_data.get("module")
        date_reference = serializer.validated_data.get(
            "date_reference"
        )

        try:
            if module:
                decision = ImpactMedicalService.decision_pour_module(
                    affectation_centre_id=affectation_centre_id,
                    module=module,
                    date_reference=date_reference,
                )
                return Response(
                    DecisionMedicaleSerializer(decision).data
                )

            decisions = ImpactMedicalService.toutes_les_decisions(
                affectation_centre_id=affectation_centre_id,
                date_reference=date_reference,
            )
        except (
            DjangoValidationError,
            ValidationSanteErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(decisions)
