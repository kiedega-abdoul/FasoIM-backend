from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.response import Response

from .models import AlerteIncident
from .permissions import PermissionAlerteIncident, PermissionOperationIncident
from .repository import AlerteIncidentRepository
from .serializers import (
    AlerteIncidentSerializer,
    FiltreIncidentSerializer,
    LancerScanSerializer,
    ModificationSignalementSerializer,
    MotifIncidentSerializer,
    ObservationIncidentSerializer,
    ProgressionIncidentSerializer,
    ResolutionIncidentSerializer,
    SignalementIncidentSerializer,
    StatistiquesIncidentQuerySerializer,
    TacheIncidentLanceeSerializer,
)
from .service import AlerteIncidentService, ValidationIncidentErreur
from .tasks import (
    ProgressionIncidentsService,
    escalader_retards_task,
    scanner_integrite_global_task,
    scanner_module_task,
)


def _convertir_erreur(exception):
    if hasattr(exception, "message_dict"):
        return exception.message_dict
    if hasattr(exception, "messages"):
        return exception.messages
    return str(exception)


def _lever_erreur(exception):
    if isinstance(exception, (DjangoValidationError, ValidationIncidentErreur)):
        raise ValidationError(_convertir_erreur(exception))
    if isinstance(exception, IntegrityError):
        raise ValidationError(
            {"detail": "Cette opération entre en conflit avec un incident existant."}
        )
    raise exception


class AlerteIncidentViewSet(viewsets.ModelViewSet):
    permission_classes = [PermissionAlerteIncident]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self):
        visibles = AlerteIncidentRepository.visibles_pour(self.request.user)
        if self.kwargs.get("pk"):
            return visibles

        filtre = FiltreIncidentSerializer(data=self.request.query_params)
        filtre.is_valid(raise_exception=True)
        ids_visibles = visibles.values("id")
        return AlerteIncidentRepository.filtrer(
            **filtre.validated_data
        ).filter(id__in=ids_visibles)

    def get_serializer_class(self):
        if self.action == "create":
            return SignalementIncidentSerializer
        if self.action in {"update", "partial_update"}:
            return ModificationSignalementSerializer
        if self.action in {"mettre_en_attente", "annuler", "escalader"}:
            return MotifIncidentSerializer
        if self.action == "resoudre":
            return ResolutionIncidentSerializer
        if self.action in {"prendre_en_charge", "cloturer"}:
            return ObservationIncidentSerializer
        if self.action == "statistiques":
            return StatistiquesIncidentQuerySerializer
        return AlerteIncidentSerializer

    def create(self, request, *args, **kwargs):
        serializer = SignalementIncidentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            incident = AlerteIncidentService.signaler_manuellement(
                acteur=request.user,
                **serializer.validated_data,
            )
        except (DjangoValidationError, ValidationIncidentErreur, IntegrityError) as exception:
            _lever_erreur(exception)
        return Response(
            AlerteIncidentSerializer(incident, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        incident = self.get_object()
        serializer = ModificationSignalementSerializer(
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        try:
            incident = AlerteIncidentService.modifier_signalement(
                incident.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (DjangoValidationError, ValidationIncidentErreur, IntegrityError) as exception:
            _lever_erreur(exception)
        return Response(AlerteIncidentSerializer(incident, context={"request": request}).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail="Un incident ne se supprime pas depuis l'API.")

    @action(detail=True, methods=["post"], url_path="prendre-en-charge")
    def prendre_en_charge(self, request, pk=None):
        incident = self.get_object()
        serializer = ObservationIncidentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            incident = AlerteIncidentService.prendre_en_charge(
                incident.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (DjangoValidationError, ValidationIncidentErreur, IntegrityError) as exception:
            _lever_erreur(exception)
        return Response(AlerteIncidentSerializer(incident, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="mettre-en-attente")
    def mettre_en_attente(self, request, pk=None):
        incident = self.get_object()
        serializer = MotifIncidentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            incident = AlerteIncidentService.mettre_en_attente(
                incident.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (DjangoValidationError, ValidationIncidentErreur, IntegrityError) as exception:
            _lever_erreur(exception)
        return Response(AlerteIncidentSerializer(incident, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="resoudre")
    def resoudre(self, request, pk=None):
        incident = self.get_object()
        serializer = ResolutionIncidentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            incident = AlerteIncidentService.resoudre(
                incident.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (DjangoValidationError, ValidationIncidentErreur, IntegrityError) as exception:
            _lever_erreur(exception)
        return Response(AlerteIncidentSerializer(incident, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="cloturer")
    def cloturer(self, request, pk=None):
        incident = self.get_object()
        serializer = ObservationIncidentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            incident = AlerteIncidentService.cloturer(
                incident.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (DjangoValidationError, ValidationIncidentErreur, IntegrityError) as exception:
            _lever_erreur(exception)
        return Response(AlerteIncidentSerializer(incident, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="annuler")
    def annuler(self, request, pk=None):
        incident = self.get_object()
        serializer = MotifIncidentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            incident = AlerteIncidentService.annuler(
                incident.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (DjangoValidationError, ValidationIncidentErreur, IntegrityError) as exception:
            _lever_erreur(exception)
        return Response(AlerteIncidentSerializer(incident, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="escalader")
    def escalader(self, request, pk=None):
        incident = self.get_object()
        serializer = MotifIncidentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            incident = AlerteIncidentService.escalader(
                incident.id,
                acteur=request.user,
                **serializer.validated_data,
            )
        except (DjangoValidationError, ValidationIncidentErreur, IntegrityError) as exception:
            _lever_erreur(exception)
        return Response(AlerteIncidentSerializer(incident, context={"request": request}).data)

    @action(detail=False, methods=["get"], url_path="statistiques")
    def statistiques(self, request):
        serializer = StatistiquesIncidentQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        visibles = AlerteIncidentRepository.visibles_pour(request.user)
        qs = visibles
        if serializer.validated_data.get("session_id"):
            qs = qs.filter(session_id=serializer.validated_data["session_id"])
        if serializer.validated_data.get("centre_id"):
            qs = qs.filter(centre_id=serializer.validated_data["centre_id"])
        donnees = AlerteIncidentRepository.statistiques(queryset=qs)
        return Response(donnees)


class OperationIncidentViewSet(viewsets.ViewSet):
    permission_classes = [PermissionOperationIncident]

    @action(detail=False, methods=["post"], url_path="lancer-scan")
    def lancer_scan(self, request):
        serializer = LancerScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        module = serializer.validated_data.get("module", "tous")
        if module == "tous":
            tache = scanner_integrite_global_task.delay()
            operation = "scan_global"
        else:
            tache = scanner_module_task.delay(module=module)
            operation = f"scan_{module}"
        donnees = {
            "task_id": str(tache.id),
            "operation": operation,
            "statut": ProgressionIncidentsService.EN_ATTENTE,
        }
        return Response(
            TacheIncidentLanceeSerializer(donnees).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"progression/(?P<task_id>[^/.]+)",
    )
    def progression(self, request, task_id=None):
        donnees = ProgressionIncidentsService.lire(task_id)
        return Response(ProgressionIncidentSerializer(donnees).data)

    @action(detail=False, methods=["post"], url_path="escalader-retards")
    def escalader_retards(self, request):
        tache = escalader_retards_task.delay()
        donnees = {
            "task_id": str(tache.id),
            "operation": "escalade_retards",
            "statut": ProgressionIncidentsService.EN_ATTENTE,
        }
        return Response(
            TacheIncidentLanceeSerializer(donnees).data,
            status=status.HTTP_202_ACCEPTED,
        )
