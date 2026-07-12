from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.models import Acteur
from accounts.repository import AffectationActeurRepository, ControleAccesRepository
from accounts.service import ControleAccesService

from .models import AlerteIncident


def _entier(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def contexte_incident(obj):
    if not isinstance(obj, AlerteIncident):
        return {"session_id": None, "centre_id": None, "region_code": None}
    region_code = None
    if obj.centre_id and obj.centre:
        region_code = obj.centre.region.code
    return {
        "session_id": obj.session_id,
        "centre_id": obj.centre_id,
        "region_code": region_code,
    }


def extraire_perimetre(request, view=None, obj=None):
    if obj is not None:
        return contexte_incident(obj)

    source = getattr(request, "data", {}) or {}
    query = getattr(request, "query_params", {}) or {}
    session_id = _entier(source.get("session_id") or query.get("session_id"))
    centre_id = _entier(source.get("centre_id") or query.get("centre_id"))

    pk = getattr(view, "kwargs", {}).get("pk") if view else None
    if pk and not (session_id or centre_id):
        incident = AlerteIncident.objects.select_related("centre__region").filter(
            id=pk,
            deleted_at__isnull=True,
        ).first()
        if incident:
            return contexte_incident(incident)

    return {"session_id": session_id, "centre_id": centre_id, "region_code": None}


class PermissionIncidentBase(BasePermission):
    message = "Permission incident absente ou hors périmètre."
    action_permission_map = {}

    def _acteur_valide(self, acteur):
        return bool(
            acteur
            and acteur.is_authenticated
            and isinstance(acteur, Acteur)
            and acteur.is_active
            and acteur.statut == Acteur.Statut.ACTIF
            and acteur.deleted_at is None
        )

    def get_code_permission(self, request, view):
        return self.action_permission_map.get(getattr(view, "action", None))

    def has_permission(self, request, view):
        acteur = getattr(request, "user", None)
        if not self._acteur_valide(acteur):
            self.message = "Acteur non authentifié, inactif ou supprimé."
            return False
        if acteur.is_superuser:
            return True
        code = self.get_code_permission(request, view)
        if not code:
            self.message = "Aucune permission n'est configurée pour cette action."
            return False
        perimetre = extraire_perimetre(request, view)
        if not any(perimetre.values()):
            # La liste, le signalement rapide et la progression ne portent pas
            # toujours un périmètre explicite dans l'URL. On vérifie alors que
            # la permission existe dans au moins une affectation active; le
            # service métier contrôlera ensuite le concerné exact.
            for affectation in AffectationActeurRepository.lister_actives_par_acteur(acteur):
                if ControleAccesRepository.acteur_a_permission(acteur, affectation, code):
                    return True
            self.message = "Permission absente dans les affectations actives."
            return False

        resultat = ControleAccesService.acteur_peut(
            acteur,
            code,
            **perimetre,
        )
        if not resultat.autorise:
            self.message = resultat.motif or self.message
        return resultat.autorise

    def has_object_permission(self, request, view, obj):
        acteur = getattr(request, "user", None)
        if not self._acteur_valide(acteur):
            return False
        if acteur.is_superuser:
            return True
        code = self.get_code_permission(request, view)
        resultat = ControleAccesService.acteur_peut(
            acteur,
            code,
            **extraire_perimetre(request, view, obj=obj),
        )
        if not resultat.autorise:
            self.message = resultat.motif or self.message
        return resultat.autorise


class PermissionAlerteIncident(PermissionIncidentBase):
    action_permission_map = {
        "list": "consulter_incidents",
        "retrieve": "consulter_incidents",
        "create": "signaler_incident",
        "update": "modifier_incident",
        "partial_update": "modifier_incident",
        "prendre_en_charge": "prendre_en_charge_incident",
        "mettre_en_attente": "mettre_incident_en_attente",
        "resoudre": "resoudre_incident",
        "cloturer": "cloturer_incident",
        "annuler": "annuler_incident",
        "escalader": "escalader_incident",
        "statistiques": "consulter_incidents",
    }


class PermissionOperationIncident(PermissionIncidentBase):
    action_permission_map = {
        "lancer_scan": "generer_alerte_automatique",
        "progression": "generer_alerte_automatique",
        "escalader_retards": "escalader_incident",
    }
