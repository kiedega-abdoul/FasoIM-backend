from __future__ import annotations

import re
import unicodedata

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from .models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)
from .permissions import (
    PermissionAffectationCentre,
    PermissionAffectationRegionale,
    PermissionCentreImmersion,
    PermissionRegionImmersion,
    extraire_perimetre_affectation,
)
from .repository import (
    AffectationCentreRepository,
    AffectationRegionaleRepository,
    CentreImmersionRepository,
    RegionImmersionRepository,
)
from .serializers import (
    ActionAffectationsLotInputSerializer,
    AffectationCentreManuelleInputSerializer,
    AffectationCentreSerializer,
    AffectationRegionaleManuelleInputSerializer,
    AffectationRegionaleSerializer,
    AnnulationAffectationInputSerializer,
    CentreImmersionDetailSerializer,
    CentreImmersionInputSerializer,
    CentreImmersionResumeSerializer,
    CentreImmersionUpdateSerializer,
    FiltreAffectationCentreSerializer,
    FiltreAffectationRegionaleSerializer,
    FiltreCentreImmersionSerializer,
    ProgressionAffectationSerializer,
    PropositionCentreLotInputSerializer,
    PropositionRegionaleLotInputSerializer,
    RegionImmersionDetailSerializer,
    RegionImmersionInputSerializer,
    RegionImmersionResumeSerializer,
    RegionImmersionUpdateSerializer,
    RejetAffectationsLotInputSerializer,
    TacheAffectationLanceeSerializer,
    ValidationAffectationsLotInputSerializer,
)
from .service import (
    AffectationCentreService,
    AffectationRegionaleService,
    CapaciteAffectationService,
    ProfilAffectationService,
    ValidationAffectationErreur,
)
from .tasks import (
    ProgressionAffectationService,
    proposer_affectations_centres_task,
    proposer_affectations_regionales_task,
    rejeter_affectations_centres_task,
    rejeter_affectations_regionales_task,
    valider_affectations_centres_task,
    valider_affectations_regionales_task,
)


def convertir_erreur_django(exception):
    """Convertit les erreurs Django métier en erreurs DRF lisibles."""

    if hasattr(exception, "message_dict"):
        return exception.message_dict
    if hasattr(exception, "messages"):
        return exception.messages
    return str(exception)


def lever_erreur_service(exception):
    if isinstance(exception, DjangoValidationError):
        raise ValidationError(convertir_erreur_django(exception))
    if isinstance(exception, IntegrityError):
        raise ValidationError(
            {"detail": "Cette opération entre en conflit avec une donnée existante."}
        )
    raise exception


def code_automatique(valeur, *, max_length=50):
    texte = unicodedata.normalize("NFKD", str(valeur or ""))
    texte = texte.encode("ascii", "ignore").decode("ascii")
    texte = re.sub(r"[^A-Za-z0-9]+", "_", texte).strip("_").upper()
    return (texte or "REF")[:max_length].strip("_") or "REF"


def code_unique(base, existe_code, *, max_length=50):
    racine = code_automatique(base, max_length=max_length)
    code = racine
    compteur = 2
    while existe_code(code):
        suffixe = f"_{compteur}"
        code = f"{racine[:max_length - len(suffixe)]}{suffixe}"
        compteur += 1
    return code


class AffectationsViewSetBase(viewsets.GenericViewSet):
    """Outils communs aux API du module affectations."""

    def reponse_action(
        self,
        message,
        *,
        extra=None,
        statut=status.HTTP_200_OK,
    ):
        payload = {"detail": message}
        if extra:
            payload.update(extra)
        return Response(payload, status=statut)

    def lancer_tache(self, tache, *, operation, kwargs):
        """Lance Celery et renvoie immédiatement l'identifiant de suivi."""

        resultat = tache.delay(**kwargs)
        payload = {
            "task_id": str(resultat.id),
            "operation": operation,
            "message": "Traitement lancé en arrière-plan.",
        }
        serializer = TacheAffectationLanceeSerializer(payload)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

    def serialiser_avec_profils(self, objets, serializer_class, *, many):
        """Ajoute les profils sources sans provoquer une requête par ligne."""

        objets_liste = list(objets) if many else [objets]
        immerges = [
            objet.immerge
            for objet in objets_liste
            if getattr(objet, "immerge_id", None)
        ]

        if immerges:
            profils, _ = ProfilAffectationService.construire_profils(immerges)
            for objet in objets_liste:
                objet._profil_affectation = profils.get(objet.immerge_id)

        serializer = serializer_class(
            objets_liste if many else objets_liste[0],
            many=many,
            context=self.get_serializer_context(),
        )
        return serializer.data

    def verifier_objets_lot(self, request, queryset, ids):
        """Applique les permissions objet à chaque élément d'un lot."""

        ids_uniques = list(dict.fromkeys(int(valeur) for valeur in ids))
        objets = list(queryset.filter(id__in=ids_uniques).order_by("id"))

        if len(objets) != len(ids_uniques):
            raise ValidationError(
                {"affectation_ids": "Une ou plusieurs affectations sont introuvables."}
            )

        for objet in objets:
            self.check_object_permissions(request, objet)

        return objets


class RegionImmersionViewSet(AffectationsViewSetBase):
    """Référentiel des régions d'immersion."""

    permission_classes = [PermissionRegionImmersion]
    http_method_names = [
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
    ]

    def get_queryset(self):
        queryset = RegionImmersionRepository.lister()
        statut_filtre = self.request.query_params.get("statut")
        recherche = self.request.query_params.get("recherche") or self.request.query_params.get("q")
        perimetre = extraire_perimetre_affectation(
            self.request,
            self,
            cible="region",
        )

        if statut_filtre:
            queryset = queryset.filter(statut=statut_filtre)

        region_code = (
            self.request.query_params.get("region_code")
            or self.request.query_params.get("code")
            or perimetre.get("region_code")
        )
        if region_code:
            queryset = queryset.filter(code=str(region_code).strip().upper())

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                nom__icontains=recherche,
            ) | queryset.filter(
                code__icontains=recherche,
            )

        return queryset.order_by("nom", "id")

    def get_serializer_class(self):
        if self.action == "list":
            return RegionImmersionResumeSerializer
        if self.action == "create":
            return RegionImmersionInputSerializer
        if self.action in {"update", "partial_update"}:
            return RegionImmersionUpdateSerializer
        return RegionImmersionDetailSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = RegionImmersionResumeSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        region = self.get_object()
        serializer = RegionImmersionDetailSerializer(
            region,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = RegionImmersionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)
        if not donnees.get("code"):
            donnees["code"] = code_unique(
                donnees["nom"],
                RegionImmersionRepository.existe_code,
            )

        if RegionImmersionRepository.existe_code(donnees["code"]):
            raise ValidationError(
                {"code": "Une région active utilise déjà ce code."}
            )

        try:
            region = RegionImmersionRepository.creer(**donnees)
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        sortie = RegionImmersionDetailSerializer(
            region,
            context=self.get_serializer_context(),
        )
        return Response(sortie.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        region = self.get_object()
        serializer = RegionImmersionUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)

        nouveau_code = donnees.get("code")
        if nouveau_code and RegionImmersionRepository.existe_code(
            nouveau_code,
            exclure_id=region.id,
        ):
            raise ValidationError(
                {"code": "Une autre région active utilise déjà ce code."}
            )

        for champ, valeur in donnees.items():
            setattr(region, champ, valeur)

        try:
            RegionImmersionRepository.sauvegarder(
                region,
                update_fields=[*donnees.keys(), "updated_at"],
            )
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        sortie = RegionImmersionDetailSerializer(
            region,
            context=self.get_serializer_context(),
        )
        return Response(sortie.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        region = self.get_object()
        try:
            region.supprimer_logiquement()
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        return self.reponse_action("Région désactivée avec succès.")

    @action(detail=True, methods=["post"], url_path="desactiver")
    def desactiver(self, request, pk=None):
        return self.destroy(request, pk=pk)


class CentreImmersionViewSet(AffectationsViewSetBase):
    """Référentiel et capacité des centres d'immersion."""

    permission_classes = [PermissionCentreImmersion]
    http_method_names = [
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
    ]

    def get_queryset(self):
        filtre = FiltreCentreImmersionSerializer(
            data=self.request.query_params,
        )
        filtre.is_valid(raise_exception=True)
        donnees = dict(filtre.validated_data)
        perimetre = extraire_perimetre_affectation(
            self.request,
            self,
            cible="centre",
        )
        donnees.setdefault("region_code", perimetre.get("region_code"))
        donnees.setdefault("centre_id", perimetre.get("centre_id"))
        return CentreImmersionRepository.filtrer(**donnees)

    def get_serializer_class(self):
        if self.action == "list":
            return CentreImmersionResumeSerializer
        if self.action == "create":
            return CentreImmersionInputSerializer
        if self.action in {"update", "partial_update"}:
            return CentreImmersionUpdateSerializer
        return CentreImmersionDetailSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = CentreImmersionResumeSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        centre = self.get_object()
        serializer = CentreImmersionDetailSerializer(
            centre,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = CentreImmersionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)
        region_id = donnees.pop("region_id")

        try:
            region = RegionImmersionRepository.get_by_id(region_id)
        except RegionImmersion.DoesNotExist as exception:
            raise ValidationError(
                {"region_id": "La région demandée est introuvable ou inactive."}
            ) from exception

        if not donnees.get("code"):
            donnees["code"] = code_unique(
                f"{region.code}_{donnees['nom']}",
                CentreImmersionRepository.existe_code,
            )

        if CentreImmersionRepository.existe_code(donnees["code"]):
            raise ValidationError(
                {"code": "Un centre actif utilise déjà ce code."}
            )

        try:
            centre = CentreImmersionRepository.creer(
                region=region,
                **donnees,
            )
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        sortie = CentreImmersionDetailSerializer(
            centre,
            context=self.get_serializer_context(),
        )
        return Response(sortie.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        centre = self.get_object()
        serializer = CentreImmersionUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)

        nouveau_code = donnees.get("code")
        if nouveau_code and CentreImmersionRepository.existe_code(
            nouveau_code,
            exclure_id=centre.id,
        ):
            raise ValidationError(
                {"code": "Un autre centre actif utilise déjà ce code."}
            )

        champs_modifies = []
        region_id = donnees.pop("region_id", None)
        if region_id is not None:
            try:
                centre.region = RegionImmersionRepository.get_by_id(region_id)
            except RegionImmersion.DoesNotExist as exception:
                raise ValidationError(
                    {"region_id": "La région demandée est introuvable ou inactive."}
                ) from exception
            champs_modifies.append("region")

        for champ, valeur in donnees.items():
            setattr(centre, champ, valeur)
            champs_modifies.append(champ)

        try:
            CentreImmersionRepository.sauvegarder(
                centre,
                update_fields=[*champs_modifies, "updated_at"],
            )
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        sortie = CentreImmersionDetailSerializer(
            centre,
            context=self.get_serializer_context(),
        )
        return Response(sortie.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        centre = self.get_object()
        try:
            centre.supprimer_logiquement()
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        return self.reponse_action("Centre désactivé avec succès.")

    @action(detail=True, methods=["post"], url_path="desactiver")
    def desactiver(self, request, pk=None):
        return self.destroy(request, pk=pk)

    @action(detail=True, methods=["post"], url_path="mettre-en-maintenance")
    def mettre_en_maintenance(self, request, pk=None):
        centre = self.get_object()
        centre.statut = CentreImmersion.Statut.MAINTENANCE

        try:
            CentreImmersionRepository.sauvegarder(
                centre,
                update_fields=["statut", "updated_at"],
            )
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        sortie = CentreImmersionDetailSerializer(
            centre,
            context=self.get_serializer_context(),
        )
        return self.reponse_action(
            "Centre placé en maintenance.",
            extra={"centre": sortie.data},
        )

    @action(detail=True, methods=["post"], url_path="reactiver")
    def reactiver(self, request, pk=None):
        centre = self.get_object()

        if not centre.region.est_active:
            raise ValidationError(
                {"region": "La région du centre doit être active."}
            )

        centre.statut = CentreImmersion.Statut.ACTIF
        try:
            CentreImmersionRepository.sauvegarder(
                centre,
                update_fields=["statut", "updated_at"],
            )
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        sortie = CentreImmersionDetailSerializer(
            centre,
            context=self.get_serializer_context(),
        )
        return self.reponse_action(
            "Centre réactivé avec succès.",
            extra={"centre": sortie.data},
        )

    @action(detail=True, methods=["get"], url_path="verifier-capacite")
    def verifier_capacite(self, request, pk=None):
        centre = self.get_object()
        session_id = request.query_params.get("session_id")

        if not session_id:
            raise ValidationError(
                {"session_id": "La session est obligatoire pour calculer l'occupation."}
            )

        donnees_centre = {
            "id": centre.id,
        }
        capacites = CapaciteAffectationService.capacites_centres(
            session_id=int(session_id),
            centres=[donnees_centre],
            region_id=centre.region_id,
        )

        return Response(
            {
                "centre_id": centre.id,
                "session_id": int(session_id),
                **capacites[centre.id],
            }
        )


class AffectationRegionaleViewSet(AffectationsViewSetBase):
    """Propositions, validations et affectations régionales manuelles."""

    permission_classes = [PermissionAffectationRegionale]
    http_method_names = [
        "get",
        "post",
        "delete",
        "head",
        "options",
    ]

    def get_queryset(self):
        filtre = FiltreAffectationRegionaleSerializer(
            data=self.request.query_params,
        )
        filtre.is_valid(raise_exception=True)
        return AffectationRegionaleRepository.filtrer(**filtre.validated_data)

    def get_serializer_class(self):
        if self.action in {"create", "affecter_manuellement"}:
            return AffectationRegionaleManuelleInputSerializer
        if self.action == "proposer_lot":
            return PropositionRegionaleLotInputSerializer
        if self.action == "valider_lot":
            return ValidationAffectationsLotInputSerializer
        if self.action == "rejeter_lot":
            return RejetAffectationsLotInputSerializer
        if self.action == "annuler":
            return AnnulationAffectationInputSerializer
        if self.action == "progression":
            return ProgressionAffectationSerializer
        return AffectationRegionaleSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            donnees = self.serialiser_avec_profils(
                page,
                AffectationRegionaleSerializer,
                many=True,
            )
            return self.get_paginated_response(donnees)

        donnees = self.serialiser_avec_profils(
            queryset,
            AffectationRegionaleSerializer,
            many=True,
        )
        return Response(donnees)

    def retrieve(self, request, *args, **kwargs):
        affectation = self.get_object()
        donnees = self.serialiser_avec_profils(
            affectation,
            AffectationRegionaleSerializer,
            many=False,
        )
        return Response(donnees)

    def create(self, request, *args, **kwargs):
        serializer = AffectationRegionaleManuelleInputSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        try:
            affectation = AffectationRegionaleService.proposer_manuellement(
                **serializer.validated_data,
                acteur=request.user,
            )
        except (DjangoValidationError, ValidationAffectationErreur, IntegrityError) as exception:
            lever_erreur_service(exception)

        donnees = self.serialiser_avec_profils(
            affectation,
            AffectationRegionaleSerializer,
            many=False,
        )
        return Response(donnees, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="affecter-manuellement")
    def affecter_manuellement(self, request):
        return self.create(request)

    @action(detail=False, methods=["post"], url_path="proposer-lot")
    def proposer_lot(self, request):
        serializer = PropositionRegionaleLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return self.lancer_tache(
            proposer_affectations_regionales_task,
            operation="proposition_affectations_regionales",
            kwargs={
                **serializer.validated_data,
                "acteur_id": request.user.id,
            },
        )

    @action(detail=False, methods=["post"], url_path="valider-lot")
    def valider_lot(self, request):
        serializer = ValidationAffectationsLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["affectation_ids"]

        self.verifier_objets_lot(
            request,
            AffectationRegionaleRepository.actifs(),
            ids,
        )

        return self.lancer_tache(
            valider_affectations_regionales_task,
            operation="validation_affectations_regionales",
            kwargs={
                "affectation_ids": ids,
                "acteur_id": request.user.id,
                "motif": serializer.validated_data.get("motif", ""),
            },
        )

    @action(detail=False, methods=["post"], url_path="rejeter-lot")
    def rejeter_lot(self, request):
        serializer = RejetAffectationsLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["affectation_ids"]

        self.verifier_objets_lot(
            request,
            AffectationRegionaleRepository.actifs(),
            ids,
        )

        return self.lancer_tache(
            rejeter_affectations_regionales_task,
            operation="rejet_affectations_regionales",
            kwargs={
                "affectation_ids": ids,
                "motif": serializer.validated_data["motif"],
            },
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"progression/(?P<task_id>[^/.]+)",
    )
    def progression(self, request, task_id=None):
        donnees = ProgressionAffectationService.lire(task_id)
        serializer = ProgressionAffectationSerializer(donnees)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="annuler")
    def annuler(self, request, pk=None):
        affectation = self.get_object()
        serializer = AnnulationAffectationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            affectation.annuler(serializer.validated_data["motif"])
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        return self.reponse_action("Affectation régionale annulée.")

    def destroy(self, request, *args, **kwargs):
        affectation = self.get_object()
        try:
            affectation.annuler("Annulation depuis la suppression API.")
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return self.reponse_action("Affectation régionale annulée.")


class AffectationCentreViewSet(AffectationsViewSetBase):
    """Propositions, validations et affectations manuelles aux centres."""

    permission_classes = [PermissionAffectationCentre]
    http_method_names = [
        "get",
        "post",
        "delete",
        "head",
        "options",
    ]

    def get_queryset(self):
        filtre = FiltreAffectationCentreSerializer(
            data=self.request.query_params,
        )
        filtre.is_valid(raise_exception=True)
        return AffectationCentreRepository.filtrer(**filtre.validated_data)

    def get_serializer_class(self):
        if self.action in {"create", "affecter_manuellement"}:
            return AffectationCentreManuelleInputSerializer
        if self.action == "proposer_lot":
            return PropositionCentreLotInputSerializer
        if self.action == "valider_lot":
            return ValidationAffectationsLotInputSerializer
        if self.action == "rejeter_lot":
            return RejetAffectationsLotInputSerializer
        if self.action == "annuler":
            return AnnulationAffectationInputSerializer
        if self.action == "progression":
            return ProgressionAffectationSerializer
        return AffectationCentreSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            donnees = self.serialiser_avec_profils(
                page,
                AffectationCentreSerializer,
                many=True,
            )
            return self.get_paginated_response(donnees)

        donnees = self.serialiser_avec_profils(
            queryset,
            AffectationCentreSerializer,
            many=True,
        )
        return Response(donnees)

    def retrieve(self, request, *args, **kwargs):
        affectation = self.get_object()
        donnees = self.serialiser_avec_profils(
            affectation,
            AffectationCentreSerializer,
            many=False,
        )
        return Response(donnees)

    def create(self, request, *args, **kwargs):
        serializer = AffectationCentreManuelleInputSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        try:
            affectation = AffectationCentreService.proposer_manuellement(
                **serializer.validated_data,
                acteur=request.user,
            )
        except (DjangoValidationError, ValidationAffectationErreur, IntegrityError) as exception:
            lever_erreur_service(exception)

        donnees = self.serialiser_avec_profils(
            affectation,
            AffectationCentreSerializer,
            many=False,
        )
        return Response(donnees, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="affecter-manuellement")
    def affecter_manuellement(self, request):
        return self.create(request)

    @action(detail=False, methods=["post"], url_path="proposer-lot")
    def proposer_lot(self, request):
        serializer = PropositionCentreLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return self.lancer_tache(
            proposer_affectations_centres_task,
            operation="proposition_affectations_centres",
            kwargs={
                **serializer.validated_data,
                "acteur_id": request.user.id,
            },
        )

    @action(detail=False, methods=["post"], url_path="valider-lot")
    def valider_lot(self, request):
        serializer = ValidationAffectationsLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["affectation_ids"]

        self.verifier_objets_lot(
            request,
            AffectationCentreRepository.actifs(),
            ids,
        )

        return self.lancer_tache(
            valider_affectations_centres_task,
            operation="validation_affectations_centres",
            kwargs={
                "affectation_ids": ids,
                "acteur_id": request.user.id,
                "motif": serializer.validated_data.get("motif", ""),
            },
        )

    @action(detail=False, methods=["post"], url_path="rejeter-lot")
    def rejeter_lot(self, request):
        serializer = RejetAffectationsLotInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["affectation_ids"]

        self.verifier_objets_lot(
            request,
            AffectationCentreRepository.actifs(),
            ids,
        )

        return self.lancer_tache(
            rejeter_affectations_centres_task,
            operation="rejet_affectations_centres",
            kwargs={
                "affectation_ids": ids,
                "motif": serializer.validated_data["motif"],
            },
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"progression/(?P<task_id>[^/.]+)",
    )
    def progression(self, request, task_id=None):
        donnees = ProgressionAffectationService.lire(task_id)
        serializer = ProgressionAffectationSerializer(donnees)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="annuler")
    def annuler(self, request, pk=None):
        affectation = self.get_object()
        serializer = AnnulationAffectationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            affectation.annuler(serializer.validated_data["motif"])
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)

        return self.reponse_action("Affectation centre annulée.")

    def destroy(self, request, *args, **kwargs):
        affectation = self.get_object()
        try:
            affectation.annuler("Annulation depuis la suppression API.")
        except (DjangoValidationError, IntegrityError) as exception:
            lever_erreur_service(exception)
        return self.reponse_action("Affectation centre annulée.")
