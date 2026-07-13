from __future__ import annotations

import hashlib

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.service import JournalActionService

from .permissions import EstActeurNotificationsActif, PermissionNotifications
from .repository import NotificationRepository
from .serializers import RelancerEmailSerializer, TestEmailSerializer
from .service import TypesMessage
from .tasks import envoyer_email_task, lire_progression


class TestEmailView(APIView):
    permission_classes = [EstActeurNotificationsActif, PermissionNotifications]
    action_code = "tester"

    def post(self, request):
        serializer = TestEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        acteur = request.user
        email = NotificationRepository.email_valide(acteur.email)
        if not email:
            return Response(
                {"detail": "Votre compte ne possède pas d'adresse e-mail valide."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        sujet = serializer.validated_data["sujet"]
        message = serializer.validated_data["message"]
        cle_evenement = serializer.validated_data.get("cle_evenement") or (
            f"TEST:{acteur.id}:"
            f"{hashlib.sha256((sujet + '|' + message).encode()).hexdigest()}"
        )
        resultat = envoyer_email_task.delay(
            {
                "destinataire": email,
                "sujet": sujet,
                "message": message,
                "type_message": TypesMessage.EMAIL_TEST,
                "cle_evenement": cle_evenement,
                "acteur_id": acteur.id,
                "contexte": {"declenche_par_id": acteur.id, "mode_contact": "DIRECT"},
            }
        )
        return Response(
            {"task_id": resultat.id, "message": "E-mail de test planifié."},
            status=status.HTTP_202_ACCEPTED,
        )


class RelancerEmailView(APIView):
    permission_classes = [EstActeurNotificationsActif, PermissionNotifications]
    action_code = "relancer"

    def post(self, request):
        serializer = RelancerEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        payload.pop("cle_deduplication_calculee", None)
        payload["contexte"] = {
            **(payload.get("contexte") or {}),
            "relance_demandee_par_id": request.user.id,
        }
        resultat = envoyer_email_task.delay(payload)
        JournalActionService.journaliser_succes(
            code_action="relancer_email_echoue",
            module_source="notifications",
            acteur=request.user,
            request=request,
            contexte={
                "task_id_notification": resultat.id,
                "cle_evenement": payload["cle_evenement"],
            },
        )
        return Response(
            {"task_id": resultat.id, "message": "Relance planifiée."},
            status=status.HTTP_202_ACCEPTED,
        )


class StatistiquesNotificationsView(APIView):
    permission_classes = [EstActeurNotificationsActif, PermissionNotifications]
    action_code = "statistiques"

    def get(self, request):
        return Response(NotificationRepository.statistiques_visibles(request.user, request.query_params))


class ProgressionNotificationsView(APIView):
    permission_classes = [EstActeurNotificationsActif, PermissionNotifications]
    action_code = "progression"

    def get(self, request, task_id):
        return Response(lire_progression(task_id))
