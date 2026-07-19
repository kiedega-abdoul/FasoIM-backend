"""Permissions DRF et extraction du périmètre du module repas."""

from rest_framework.permissions import BasePermission

from accounts.models import Acteur
from accounts.service import ControleAccesService

from .models import (
    DemandeRavitaillementCentre,
    LigneBesoinDenree,
    RepasJournalier,
    SuiviRepas,
)


def _entier(valeur):
    try:
        return int(valeur) if valeur not in (None, "") else None
    except (TypeError, ValueError):
        return None


def contexte_objet(obj):
    if isinstance(obj, DemandeRavitaillementCentre):
        return obj.session_id, obj.centre_id
    if isinstance(obj, LigneBesoinDenree):
        demande = obj.demande_ravitaillement
        return demande.session_id, demande.centre_id
    if isinstance(obj, RepasJournalier):
        return obj.session_id, obj.centre_id
    if isinstance(obj, SuiviRepas):
        return obj.repas_journalier.session_id, obj.repas_journalier.centre_id
    return None, None


def _contexte_pk(cible, pk):
    pk = _entier(pk)
    if not pk:
        return None, None
    modele = {
        "demande": DemandeRavitaillementCentre,
        "denree": LigneBesoinDenree,
        "repas": RepasJournalier,
        "suivi": SuiviRepas,
    }.get(cible)
    if modele is None:
        return None, None
    objet = modele.objects.filter(id=pk, deleted_at__isnull=True).first()
    return contexte_objet(objet) if objet else (None, None)


def extraire_perimetre(request, view=None, obj=None, cible=""):
    if obj is not None:
        session_id, centre_id = contexte_objet(obj)
        return {"session_id": session_id, "centre_id": centre_id}

    source = getattr(request, "data", {}) or {}
    query = getattr(request, "query_params", {}) or {}
    session_id = _entier(source.get("session_id") or query.get("session_id"))
    centre_id = _entier(source.get("centre_id") or query.get("centre_id"))

    demande_id = _entier(
        source.get("demande_ravitaillement_id")
        or source.get("demande_id")
        or query.get("demande_id")
    )
    repas_id = _entier(source.get("repas_id") or query.get("repas_id"))
    if demande_id and not session_id:
        demande = DemandeRavitaillementCentre.objects.filter(
            id=demande_id, deleted_at__isnull=True
        ).only("session_id", "centre_id").first()
        if demande:
            session_id, centre_id = demande.session_id, demande.centre_id
    if repas_id and not session_id:
        repas = RepasJournalier.objects.select_related(
            "demande_ravitaillement"
        ).filter(id=repas_id, deleted_at__isnull=True).first()
        if repas:
            session_id, centre_id = repas.session_id, repas.centre_id

    pk = getattr(view, "kwargs", {}).get("pk") if view else None
    if pk and not session_id:
        session_id, centre_id = _contexte_pk(cible, pk)
    return {"session_id": session_id, "centre_id": centre_id}


class PermissionRepasBase(BasePermission):
    message = "Permission repas absente ou hors périmètre."
    action_permission_map = {}
    cible = ""

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
        resultat = ControleAccesService.acteur_peut(
            acteur,
            code,
            **extraire_perimetre(request, view, cible=self.cible),
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
            **extraire_perimetre(request, view, obj=obj, cible=self.cible),
        )
        if not resultat.autorise:
            self.message = resultat.motif or self.message
        return resultat.autorise


class PermissionDemandeRavitaillement(PermissionRepasBase):
    cible = "demande"
    action_permission_map = {
        "list": "consulter_demandes_ravitaillement",
        "retrieve": "consulter_demandes_ravitaillement",
        "create": "creer_demande_ravitaillement",
        "update": "modifier_demande_ravitaillement",
        "partial_update": "modifier_demande_ravitaillement",
        "destroy": "modifier_demande_ravitaillement",
        "soumettre": "soumettre_demande_ravitaillement",
        "valider": "valider_demande_ravitaillement",
        "ajouter_denree": "modifier_demande_ravitaillement",
    }


class PermissionLigneDenree(PermissionRepasBase):
    cible = "denree"
    action_permission_map = {
        "list": "consulter_demandes_ravitaillement",
        "retrieve": "consulter_demandes_ravitaillement",
        "update": "modifier_demande_ravitaillement",
        "partial_update": "modifier_demande_ravitaillement",
        "destroy": "modifier_demande_ravitaillement",
        "reception": "enregistrer_reception_denrees",
    }


class PermissionRepasJournalier(PermissionRepasBase):
    cible = "repas"
    action_permission_map = {
        "list": "consulter_repas",
        "retrieve": "consulter_repas",
        "create": "planifier_repas",
        "update": "modifier_repas",
        "partial_update": "modifier_repas",
        "actualiser_sante": "calculer_portions_repas",
        "planifier": "planifier_repas",
        "valider_planification": "modifier_repas",
        "demarrer_preparation": "modifier_repas",
        "terminer_preparation": "modifier_repas",
        "ouvrir_distribution": "ouvrir_distribution_repas",
        "annuler": "annuler_repas",
        "statistiques": "generer_rapport_repas",
    }


class PermissionSuiviRepas(PermissionRepasBase):
    cible = "suivi"
    action_permission_map = {
        "list": "consulter_pointages_repas",
        "retrieve": "consulter_pointages_repas",
        "saisir_comptage": "pointer_repas",
        "marquer_service": "pointer_repas",
    }


class PermissionOperationRepas(PermissionRepasBase):
    cible = "operation"
    action_permission_map = {
        "retrieve": "consulter_progression_repas",
        "preparer_suivis": "ouvrir_distribution_repas",
        "actualiser_sante": "calculer_portions_repas",
        "cloturer": "cloturer_distribution_repas",
        "rapport": "generer_rapport_repas",
        "consolider_denrees": "consolider_besoins_denrees",
    }
