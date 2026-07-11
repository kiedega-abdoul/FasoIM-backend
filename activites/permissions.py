"""Permissions DRF du bloc activités."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.models import Acteur
from accounts.service import ControleAccesService
from affectations.models import AffectationCentre, CentreImmersion

from .models import (
    Evaluation,
    ModuleActivite,
    Note,
    Presence,
    Seance,
)


class PermissionActivitesBase(BasePermission):
    message = (
        "Permission activités absente ou hors périmètre."
    )
    action_permission_map = {}
    cible = ""

    def has_permission(self, request, view):
        acteur = getattr(request, "user", None)
        if not self._acteur_valide(acteur):
            self.message = (
                "Acteur non authentifié, inactif ou supprimé."
            )
            return False

        if acteur.is_superuser:
            return True

        code = self.get_code_permission(request, view)
        if not code:
            self.message = (
                "Aucune permission n'est configurée "
                "pour cette action."
            )
            return False

        resultat = ControleAccesService.acteur_peut(
            acteur,
            code,
            **extraire_perimetre_activites(
                request,
                view,
                cible=self.cible,
            ),
        )
        if not resultat.autorise:
            self.message = resultat.motif or self.message
            return False
        return True

    def has_object_permission(self, request, view, obj):
        acteur = getattr(request, "user", None)
        if not self._acteur_valide(acteur):
            self.message = (
                "Acteur non authentifié, inactif ou supprimé."
            )
            return False

        if acteur.is_superuser:
            return True

        code = self.get_code_permission(request, view)
        if not code:
            return False

        resultat = ControleAccesService.acteur_peut(
            acteur,
            code,
            **extraire_perimetre_activites(
                request,
                view,
                obj=obj,
                cible=self.cible,
            ),
        )
        if not resultat.autorise:
            self.message = resultat.motif or self.message
            return False
        return True

    @staticmethod
    def _acteur_valide(acteur):
        return bool(
            acteur
            and acteur.is_authenticated
            and isinstance(acteur, Acteur)
            and acteur.is_active
            and acteur.statut == Acteur.Statut.ACTIF
            and acteur.deleted_at is None
        )

    def get_action(self, request, view):
        return getattr(view, "action", None)

    def get_code_permission(self, request, view):
        action = self.get_action(request, view)
        mapping = getattr(
            view,
            "action_permission_map",
            None,
        )
        if mapping and action in mapping:
            return mapping[action]
        return self.action_permission_map.get(action)


class PermissionModuleActivite(PermissionActivitesBase):
    cible = "module"
    action_permission_map = {
        "list": "consulter_activites",
        "retrieve": "consulter_activites",
        "create": "creer_activite",
        "update": "modifier_activite",
        "partial_update": "modifier_activite",
        "destroy": "desactiver_activite",
        "desactiver": "desactiver_activite",
        "reactiver": "desactiver_activite",
    }


class PermissionSeance(PermissionActivitesBase):
    cible = "seance"
    action_permission_map = {
        "list": "consulter_seances",
        "retrieve": "consulter_seances",
        "create": "planifier_seance",
        "update": "modifier_seance",
        "partial_update": "modifier_seance",
        "destroy": "annuler_seance",
        "reporter": "reporter_seance",
        "affecter_formateur": (
            "affecter_formateur_seance"
        ),
    }


class PermissionPresence(PermissionActivitesBase):
    cible = "presence"
    action_permission_map = {
        "list": "consulter_presences",
        "retrieve": "consulter_presences",
        "create": "saisir_presence",
        "update": "modifier_presence",
        "partial_update": "modifier_presence",
        "ouvrir_feuille": "ouvrir_feuille_presence",
        "valider_feuille": "valider_presence",
        "cloturer_feuille": "cloturer_feuille_presence",
        "taux": "calculer_taux_presence",
        "statistiques": "consulter_presences",
    }


class PermissionEvaluation(PermissionActivitesBase):
    cible = "evaluation"
    action_permission_map = {
        "list": "consulter_evaluations",
        "retrieve": "consulter_evaluations",
        "create": "creer_evaluation",
        "update": "modifier_evaluation",
        "partial_update": "modifier_evaluation",
        "destroy": "annuler_evaluation",
        "ouvrir_saisie": "ouvrir_saisie_notes",
        "cloturer": "cloturer_evaluation",
        "valider_resultats": "valider_resultats",
        "resultats": "consulter_resultats",
    }


class PermissionNote(PermissionActivitesBase):
    cible = "note"
    action_permission_map = {
        "list": "consulter_notes",
        "retrieve": "consulter_notes",
        "create": "saisir_note",
        "update": "modifier_note",
        "partial_update": "modifier_note",
        "destroy": "annuler_note",
        "marquer_absent": "marquer_absence_note",
        "marquer_dispense": "marquer_dispense_note",
        "moyenne": "calculer_moyenne",
    }


class PermissionOperationActivite(PermissionActivitesBase):
    cible = "operation"
    action_permission_map = {
        "retrieve": "consulter_progression_activites",
        "preparer_feuille": "ouvrir_feuille_presence",
        "saisir_presences": "saisir_presence",
        "valider_feuilles": "valider_presence",
        "saisir_notes": "saisir_note",
        "valider_resultats": "valider_resultats",
        "recalculer_taux": "calculer_taux_presence",
        "recalculer_moyennes": "calculer_moyenne",
    }


def _entier_ou_none(valeur):
    try:
        return (
            int(valeur)
            if valeur not in (None, "")
            else None
        )
    except (TypeError, ValueError):
        return None


def _premiere(source, *noms):
    for nom in noms:
        valeur = source.get(nom)
        if valeur not in (None, ""):
            return valeur
    return None


def contexte_objet(obj):
    if isinstance(obj, ModuleActivite):
        return None, None

    if isinstance(obj, Seance):
        return obj.session_id, obj.centre_id

    if isinstance(obj, Presence):
        return (
            obj.seance.session_id,
            obj.seance.centre_id,
        )

    if isinstance(obj, Evaluation):
        return obj.session_id, obj.centre_id

    if isinstance(obj, Note):
        return (
            obj.evaluation.session_id,
            obj.evaluation.centre_id,
        )

    if isinstance(obj, AffectationCentre):
        return obj.session_id, obj.centre_id

    return None, None


def contexte_seance(seance_id):
    seance_id = _entier_ou_none(seance_id)
    if not seance_id:
        return None, None

    seance = Seance.objects.filter(
        id=seance_id,
        deleted_at__isnull=True,
    ).only("session_id", "centre_id").first()
    return contexte_objet(seance) if seance else (None, None)


def contexte_evaluation(evaluation_id):
    evaluation_id = _entier_ou_none(evaluation_id)
    if not evaluation_id:
        return None, None

    evaluation = Evaluation.objects.filter(
        id=evaluation_id,
        deleted_at__isnull=True,
    ).only("session_id", "centre_id").first()
    return (
        contexte_objet(evaluation)
        if evaluation
        else (None, None)
    )


def contexte_affectation(affectation_id):
    affectation_id = _entier_ou_none(affectation_id)
    if not affectation_id:
        return None, None

    affectation = AffectationCentre.objects.filter(
        id=affectation_id,
        deleted_at__isnull=True,
    ).only("session_id", "centre_id").first()
    return (
        contexte_objet(affectation)
        if affectation
        else (None, None)
    )


def contexte_pk(cible, pk):
    pk = _entier_ou_none(pk)
    if pk is None:
        return None, None

    if cible == "module":
        return None, None

    if cible == "seance":
        return contexte_seance(pk)

    if cible == "presence":
        presence = (
            Presence.objects.select_related("seance")
            .filter(
                id=pk,
                deleted_at__isnull=True,
            )
            .first()
        )
        return (
            contexte_objet(presence)
            if presence
            else (None, None)
        )

    if cible == "evaluation":
        return contexte_evaluation(pk)

    if cible == "note":
        note = (
            Note.objects.select_related("evaluation")
            .filter(
                id=pk,
                deleted_at__isnull=True,
            )
            .first()
        )
        return (
            contexte_objet(note)
            if note
            else (None, None)
        )

    return None, None


def extraire_perimetre_activites(
    request,
    view=None,
    obj=None,
    *,
    cible="",
):
    kwargs = getattr(view, "kwargs", {}) or {}
    query = getattr(request, "query_params", {}) or {}
    data = getattr(request, "data", {}) or {}

    session_id = _entier_ou_none(
        _premiere(kwargs, "session_id")
        or _premiere(query, "session_id", "session")
        or _premiere(data, "session_id", "session")
    )
    centre_id = _entier_ou_none(
        _premiere(kwargs, "centre_id")
        or _premiere(query, "centre_id", "centre")
        or _premiere(data, "centre_id", "centre")
    )

    if obj is not None:
        session_objet, centre_objet = contexte_objet(obj)
        session_id = session_objet or session_id
        centre_id = centre_objet or centre_id

    elif kwargs.get("pk") and cible != "operation":
        session_objet, centre_objet = contexte_pk(
            cible,
            kwargs["pk"],
        )
        session_id = session_objet or session_id
        centre_id = centre_objet or centre_id

    seance_id = _entier_ou_none(
        _premiere(data, "seance_id")
        or _premiere(query, "seance_id")
    )
    if seance_id:
        session_seance, centre_seance = contexte_seance(
            seance_id
        )
        session_id = session_seance or session_id
        centre_id = centre_seance or centre_id

    evaluation_id = _entier_ou_none(
        _premiere(data, "evaluation_id")
        or _premiere(query, "evaluation_id")
    )
    if evaluation_id:
        session_evaluation, centre_evaluation = (
            contexte_evaluation(evaluation_id)
        )
        session_id = session_evaluation or session_id
        centre_id = centre_evaluation or centre_id

    affectation_id = _entier_ou_none(
        _premiere(data, "affectation_centre_id")
        or _premiere(query, "affectation_centre_id")
    )
    if affectation_id:
        session_affectation, centre_affectation = (
            contexte_affectation(affectation_id)
        )
        session_id = session_affectation or session_id
        centre_id = centre_affectation or centre_id

    region_code = None
    if centre_id:
        centre = CentreImmersion.objects.select_related(
            "region"
        ).filter(
            id=centre_id,
            deleted_at__isnull=True,
        ).first()
        if centre:
            region_code = centre.region.code

    return {
        "session_id": session_id,
        "region_code": region_code,
        "centre_id": centre_id,
    }
