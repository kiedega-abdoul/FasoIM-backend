from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from .models import ArticleKit, RemiseKit
from .permissions import (
    PermissionArticleKit,
    PermissionOperationKits,
    PermissionRemiseKit,
)
from .repository import (
    ArticleKitRepository,
    RemiseKitRepository,
)
from .serializers import (
    AnnulationMasseKitsSerializer,
    ArticleKitCreateSerializer,
    ArticleKitSerializer,
    ArticleKitUpdateSerializer,
    ArticlesApplicablesQuerySerializer,
    EnregistrerRemiseArticleSerializer,
    FiltreArticleKitSerializer,
    FiltreRemiseKitSerializer,
    MarquerDispenseSerializer,
    MarquerRemplaceSerializer,
    OperationMasseKitsSerializer,
    PreparerRemiseIndividuelleSerializer,
    ProgressionTacheKitsSerializer,
    RemiseKitSerializer,
    StatistiqueRemiseKitSerializer,
    StatistiquesKitsQuerySerializer,
    StatutGlobalRemiseQuerySerializer,
    StatutGlobalRemiseSerializer,
    TacheKitsLanceeSerializer,
    ValiderRemiseCompleteSerializer,
)
from .service import (
    ArticleKitService,
    RemiseKitService,
    ValidationKitErreur,
)
from .tasks import (
    ProgressionKitsService,
    annuler_remises_lot_task,
    preparer_remises_centre_task,
    valider_remises_immerges_task,
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
        (DjangoValidationError, ValidationKitErreur),
    ):
        raise ValidationError(convertir_erreur(exception))
    if isinstance(exception, IntegrityError):
        raise ValidationError(
            {
                "detail": (
                    "Cette opération entre en conflit avec "
                    "une donnée de kit existante."
                )
            }
        )
    raise exception


class ArticleKitViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionArticleKit]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return ArticleKitRepository.non_supprimes()

        filtre = FiltreArticleKitSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return ArticleKitRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ArticleKitCreateSerializer
        if self.action in {"update", "partial_update"}:
            return ArticleKitUpdateSerializer
        if self.action == "applicables":
            return ArticlesApplicablesQuerySerializer
        return ArticleKitSerializer

    def create(self, request, *args, **kwargs):
        serializer = ArticleKitCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            article = ArticleKitService.creer(
                acteur=request.user,
                **serializer.validated_data,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            ArticleKitSerializer(article).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        article = self.get_object()
        serializer = ArticleKitUpdateSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)

        try:
            article = ArticleKitService.modifier(
                article.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(ArticleKitSerializer(article).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        article = self.get_object()

        try:
            ArticleKitService.supprimer_logiquement(
                article.id,
                acteur=request.user,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            {"detail": "Article de kit supprimé logiquement."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="desactiver")
    def desactiver(self, request, pk=None):
        article = self.get_object()

        try:
            article = ArticleKitService.desactiver(
                article.id,
                acteur=request.user,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(ArticleKitSerializer(article).data)

    @action(detail=True, methods=["post"], url_path="reactiver")
    def reactiver(self, request, pk=None):
        article = self.get_object()

        try:
            article = ArticleKitService.reactiver(
                article.id,
                acteur=request.user,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(ArticleKitSerializer(article).data)

    @action(
        detail=False,
        methods=["get"],
        url_path="applicables",
    )
    def applicables(self, request):
        serializer = ArticlesApplicablesQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        donnees = ArticleKitService.articles_pour_immerge(
            **serializer.validated_data
        )
        return Response(
            {
                "a_apporter": ArticleKitSerializer(
                    donnees["a_apporter"],
                    many=True,
                ).data,
                "a_remettre": ArticleKitSerializer(
                    donnees["a_remettre"],
                    many=True,
                ).data,
            }
        )


class RemiseKitViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [PermissionRemiseKit]

    def get_queryset(self):
        if self.kwargs.get("pk"):
            return RemiseKitRepository.actives()

        filtre = FiltreRemiseKitSerializer(
            data=self.request.query_params
        )
        filtre.is_valid(raise_exception=True)
        return RemiseKitRepository.filtrer(
            **filtre.validated_data
        )

    def get_serializer_class(self):
        if self.action == "create":
            return EnregistrerRemiseArticleSerializer
        if self.action == "preparer_individuelle":
            return PreparerRemiseIndividuelleSerializer
        if self.action == "valider_complete":
            return ValiderRemiseCompleteSerializer
        if self.action == "remplacer":
            return MarquerRemplaceSerializer
        if self.action == "dispenser":
            return MarquerDispenseSerializer
        if self.action == "statut_global":
            return StatutGlobalRemiseQuerySerializer
        if self.action == "statistiques":
            return StatistiquesKitsQuerySerializer
        return RemiseKitSerializer

    def create(self, request, *args, **kwargs):
        serializer = EnregistrerRemiseArticleSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            remise = RemiseKitService.enregistrer_remise_article(
                acteur=request.user,
                **serializer.validated_data,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            RemiseKitSerializer(remise).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="preparer-individuelle",
    )
    def preparer_individuelle(self, request):
        serializer = PreparerRemiseIndividuelleSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            resultat = RemiseKitService.preparer_remise_immerge(
                acteur=request.user,
                **serializer.validated_data,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(resultat, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=["post"],
        url_path="valider-complete",
    )
    def valider_complete(self, request):
        serializer = ValiderRemiseCompleteSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            resultat = (
                RemiseKitService
                .valider_remise_complete_immerge(
                    acteur=request.user,
                    **serializer.validated_data,
                )
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(resultat, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="remplacer")
    def remplacer(self, request, pk=None):
        remise = self.get_object()
        serializer = MarquerRemplaceSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            remise = RemiseKitService.marquer_remplace(
                remise_id=remise.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(RemiseKitSerializer(remise).data)

    @action(detail=True, methods=["post"], url_path="dispenser")
    def dispenser(self, request, pk=None):
        remise = self.get_object()
        serializer = MarquerDispenseSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            remise = RemiseKitService.marquer_dispense(
                remise_id=remise.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(RemiseKitSerializer(remise).data)

    def destroy(self, request, *args, **kwargs):
        remise = self.get_object()

        try:
            RemiseKitService.annuler_remise_logiquement(
                remise_id=remise.id,
                acteur=request.user,
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            {"detail": "Remise annulée logiquement."},
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="statut-global",
    )
    def statut_global(self, request):
        serializer = StatutGlobalRemiseQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        try:
            resultat = RemiseKitService.calculer_statut_global(
                **serializer.validated_data
            )
        except (
            DjangoValidationError,
            ValidationKitErreur,
            IntegrityError,
        ) as exception:
            lever_erreur_service(exception)

        return Response(
            StatutGlobalRemiseSerializer(resultat).data
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="statistiques",
    )
    def statistiques(self, request):
        serializer = StatistiquesKitsQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        statistiques = list(
            RemiseKitRepository.statistiques(
                **serializer.validated_data
            )
        )
        return Response(
            StatistiqueRemiseKitSerializer(
                statistiques,
                many=True,
            ).data
        )


class OperationKitsViewSet(viewsets.GenericViewSet):
    permission_classes = [PermissionOperationKits]
    lookup_value_regex = r"[^/.]+"

    @staticmethod
    def _reponse_tache(tache, operation):
        donnees = {
            "task_id": tache.id,
            "operation": operation,
            "statut": ProgressionKitsService.STATUT_EN_ATTENTE,
            "message": "La tâche a été envoyée à Celery.",
        }
        return Response(
            TacheKitsLanceeSerializer(donnees).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="preparer-masse",
    )
    def preparer_masse(self, request):
        serializer = OperationMasseKitsSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        donnees = dict(serializer.validated_data)
        tache = preparer_remises_centre_task.delay(
            acteur_id=request.user.id,
            **donnees,
        )
        return self._reponse_tache(
            tache,
            "preparer_remises_centre",
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="valider-masse",
    )
    def valider_masse(self, request):
        serializer = OperationMasseKitsSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        donnees = dict(serializer.validated_data)
        tache = valider_remises_immerges_task.delay(
            acteur_id=request.user.id,
            **donnees,
        )
        return self._reponse_tache(
            tache,
            "valider_remises_immerges",
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="annuler-masse",
    )
    def annuler_masse(self, request):
        serializer = AnnulationMasseKitsSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        donnees = dict(serializer.validated_data)
        tache = annuler_remises_lot_task.delay(
            acteur_id=request.user.id,
            **donnees,
        )
        return self._reponse_tache(
            tache,
            "annuler_remises_lot",
        )

    def retrieve(self, request, pk=None):
        progression = ProgressionKitsService.lire(pk)
        return Response(
            ProgressionTacheKitsSerializer(progression).data
        )
