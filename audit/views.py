from __future__ import annotations

from pathlib import Path

from django.core.cache import cache
from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .models import JournalAction
from .permissions import EstActeurAuditActif, PermissionAudit
from .repository import JournalActionRepository
from .serializers import (
    DemandeExportAuditSerializer,
    JournalActionDetailSerializer,
    JournalActionListeSerializer,
)
from .service import JournalActionService
from .tasks import cle_progression, generer_export_audit_task


class PaginationAudit(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class JournalActionViewSet(viewsets.ReadOnlyModelViewSet):
    """API strictement en lecture seule des journaux FasoIM."""

    permission_classes = [EstActeurAuditActif, PermissionAudit]
    pagination_class = PaginationAudit
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = JournalActionRepository.visibles_par_acteur(self.request.user)
        return JournalActionRepository.filtrer(queryset, self.request.query_params)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return JournalActionDetailSerializer
        if self.action == "exporter":
            return DemandeExportAuditSerializer
        return JournalActionListeSerializer

    @action(detail=False, methods=["get"], url_path="statistiques")
    def statistiques(self, request):
        queryset = JournalActionRepository.visibles_par_acteur(
            request.user,
            code_permission="consulter_statistiques_audit",
        )
        queryset = JournalActionRepository.filtrer(queryset, request.query_params)
        return Response(JournalActionRepository.statistiques_generales(queryset))

    @action(detail=False, methods=["get"], url_path="statistiques/immerges")
    def statistiques_immerges(self, request):
        queryset = JournalActionRepository.visibles_par_acteur(
            request.user,
            code_permission="consulter_statistiques_audit",
        )
        queryset = JournalActionRepository.filtrer(queryset, request.query_params)
        return Response(JournalActionRepository.statistiques_immerges(queryset))

    @action(detail=False, methods=["get"], url_path="statistiques/documents")
    def statistiques_documents(self, request):
        queryset = JournalActionRepository.visibles_par_acteur(
            request.user,
            code_permission="consulter_statistiques_audit",
        )
        queryset = JournalActionRepository.filtrer(queryset, request.query_params)
        return Response(JournalActionRepository.statistiques_documents(queryset))

    @action(detail=False, methods=["get"], url_path="statistiques/systeme")
    def statistiques_systeme(self, request):
        queryset = JournalActionRepository.visibles_par_acteur(
            request.user,
            code_permission="consulter_statistiques_audit",
        )
        queryset = JournalActionRepository.filtrer(queryset, request.query_params)
        return Response(JournalActionRepository.statistiques_systeme(queryset))

    @action(detail=False, methods=["get"], url_path="acces-publics")
    def acces_publics(self, request):
        queryset = JournalActionRepository.visibles_par_acteur(
            request.user,
            code_permission="consulter_audit_acces_publics",
        ).filter(
            origine__in=[JournalAction.Origine.IMMERGE, JournalAction.Origine.API_PUBLIQUE]
        )
        queryset = JournalActionRepository.filtrer(queryset, request.query_params)
        page = self.paginate_queryset(queryset)
        serializer = JournalActionListeSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @action(
        detail=False,
        methods=["get"],
        url_path=r"acteurs/(?P<acteur_id>[0-9]+)/activite",
    )
    def activite_acteur(self, request, acteur_id=None):
        queryset = JournalActionRepository.visibles_par_acteur(
            request.user,
            code_permission="consulter_activite_acteur",
        ).filter(acteur_id=acteur_id)
        queryset = JournalActionRepository.filtrer(queryset, request.query_params)
        page = self.paginate_queryset(queryset)
        serializer = JournalActionListeSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @action(
        detail=False,
        methods=["get"],
        url_path=r"immerges/(?P<immerge_id>[0-9]+)/activite",
    )
    def activite_immerge(self, request, immerge_id=None):
        queryset = JournalActionRepository.visibles_par_acteur(
            request.user,
            code_permission="consulter_activite_immerge",
        ).filter(immerge_id=immerge_id)
        queryset = JournalActionRepository.filtrer(queryset, request.query_params)
        page = self.paginate_queryset(queryset)
        serializer = JournalActionListeSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=["post"], url_path="exporter")
    def exporter(self, request):
        serializer = DemandeExportAuditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = dict(serializer.validated_data)
        format_export = donnees.pop("format", "CSV")
        filtres = {
            cle: (valeur.isoformat() if hasattr(valeur, "isoformat") else valeur)
            for cle, valeur in donnees.items()
        }
        resultat = generer_export_audit_task.delay(
            acteur_id=request.user.id,
            filtres=filtres,
            format_export=format_export,
        )
        JournalActionService.journaliser_export(
            acteur=request.user,
            code_action="demander_export_audit",
            resultat=JournalAction.Resultat.SUCCES,
            contexte={"format": format_export, "filtres": filtres},
            request=request,
            task_id=resultat.id,
        )
        return Response(
            {"task_id": resultat.id, "statut": "EN_ATTENTE", "progression": 0},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"exports/(?P<task_id>[0-9a-f-]+)/progression",
    )
    def progression_export(self, request, task_id=None):
        donnees = cache.get(cle_progression(task_id))
        if not donnees:
            return Response({"detail": "Export introuvable ou expiré."}, status=404)
        if not request.user.is_superuser and donnees.get("acteur_id") != request.user.id:
            return Response({"detail": "Cet export ne vous appartient pas."}, status=403)
        public = {cle: valeur for cle, valeur in donnees.items() if cle != "chemin"}
        return Response(public)

    @action(
        detail=False,
        methods=["get"],
        url_path=r"exports/(?P<task_id>[0-9a-f-]+)/telecharger",
    )
    def telecharger_export(self, request, task_id=None):
        donnees = cache.get(cle_progression(task_id))
        if not donnees or donnees.get("statut") != "TERMINE":
            return Response({"detail": "Export indisponible, inachevé ou expiré."}, status=404)
        if not request.user.is_superuser and donnees.get("acteur_id") != request.user.id:
            return Response({"detail": "Cet export ne vous appartient pas."}, status=403)
        chemin = Path(donnees["chemin"])
        if not chemin.is_file():
            return Response({"detail": "Le fichier d'export n'existe plus."}, status=404)
        JournalActionService.journaliser_export(
            acteur=request.user,
            code_action="telecharger_export_audit",
            resultat=JournalAction.Resultat.SUCCES,
            contexte={
                "format": donnees.get("format"),
                "total_lignes": donnees.get("total_lignes"),
                "nom_fichier": donnees.get("nom_fichier"),
            },
            request=request,
            task_id=task_id,
        )
        return FileResponse(
            chemin.open("rb"),
            as_attachment=True,
            filename=donnees.get("nom_fichier") or chemin.name,
        )
