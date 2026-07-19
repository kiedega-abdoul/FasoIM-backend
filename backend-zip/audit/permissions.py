from rest_framework.permissions import BasePermission

from accounts.models import Acteur, AffectationActeur
from accounts.repository import ControleAccesRepository
from accounts.service import ControleAccesService


class EstActeurAuditActif(BasePermission):
    message = "Acteur non authentifié ou inactif."

    def has_permission(self, request, view):
        acteur = getattr(request, "user", None)
        return bool(
            acteur
            and acteur.is_authenticated
            and isinstance(acteur, Acteur)
            and acteur.est_actif_metier
        )


class PermissionAudit(BasePermission):
    """Autorise uniquement la lecture, les statistiques et les exports."""

    message = "Permission d'audit absente ou hors périmètre."

    ACTIONS = {
        "list": "consulter_journaux_audit",
        "retrieve": "consulter_journaux_audit",
        "statistiques": "consulter_statistiques_audit",
        "statistiques_immerges": "consulter_statistiques_audit",
        "statistiques_documents": "consulter_statistiques_audit",
        "statistiques_systeme": "consulter_statistiques_audit",
        "acces_publics": "consulter_audit_acces_publics",
        "activite_acteur": "consulter_activite_acteur",
        "activite_immerge": "consulter_activite_immerge",
        "exporter": "exporter_journaux_audit",
        "progression_export": "exporter_journaux_audit",
        "telecharger_export": "exporter_journaux_audit",
    }

    def has_permission(self, request, view):
        acteur = getattr(request, "user", None)
        if not acteur or not getattr(acteur, "est_actif_metier", False):
            return False
        if acteur.is_superuser:
            return True

        action = getattr(view, "action", None)
        code = self.ACTIONS.get(action)
        if not code:
            self.message = "Cette action n'est pas autorisée dans le module audit."
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

    def has_object_permission(self, request, view, obj):
        acteur = request.user
        if acteur.is_superuser:
            return True
        region_code = (
            obj.region.code
            if obj.region_id
            else (obj.centre.region.code if obj.centre_id else None)
        )
        resultat = ControleAccesService.acteur_peut(
            acteur,
            "consulter_journaux_audit",
            session_id=obj.session_id,
            region_code=region_code,
            centre_id=obj.centre_id,
        )
        if not resultat.autorise:
            self.message = resultat.motif or self.message
        return resultat.autorise
