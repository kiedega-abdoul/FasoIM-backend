from rest_framework.permissions import BasePermission

from accounts.models import Acteur, AffectationActeur
from accounts.repository import ControleAccesRepository
from accounts.service import ControleAccesService


class EstActeurNotificationsActif(BasePermission):
    message = "Acteur non authentifié ou inactif."

    def has_permission(self, request, view):
        acteur = getattr(request, "user", None)
        return bool(
            acteur
            and acteur.is_authenticated
            and isinstance(acteur, Acteur)
            and acteur.est_actif_metier
        )


class PermissionNotifications(BasePermission):
    message = "Permission notifications absente ou hors périmètre."

    ACTIONS = {
        "tester": "envoyer_email_test",
        "relancer": "relancer_email_echoue",
        "statistiques": "consulter_statistiques_notifications",
        "progression": "consulter_statistiques_notifications",
    }

    def has_permission(self, request, view):
        acteur = getattr(request, "user", None)
        if not acteur or not getattr(acteur, "est_actif_metier", False):
            return False
        if acteur.is_superuser:
            return True

        code = self.ACTIONS.get(getattr(view, "action_code", None))
        if not code:
            self.message = "Action notifications non autorisée."
            return False

        session_id = request.query_params.get("session") or request.data.get("session")
        region_code = request.query_params.get("region_code") or request.data.get("region_code")
        centre_id = request.query_params.get("centre") or request.data.get("centre")
        if session_id or region_code or centre_id:
            resultat = ControleAccesService.acteur_peut(
                acteur,
                code,
                session_id=session_id,
                region_code=region_code,
                centre_id=centre_id,
            )
            if not resultat.autorise:
                self.message = resultat.motif or self.message
            return resultat.autorise

        affectations = AffectationActeur.objects.filter(
            acteur_id=acteur.id,
            statut=AffectationActeur.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).select_related("session")
        for affectation in affectations:
            if affectation.est_active and ControleAccesRepository.acteur_a_permission(
                acteur,
                affectation,
                code,
            ):
                return True
        return False
