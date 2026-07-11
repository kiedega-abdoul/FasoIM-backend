"""Permissions DRF du module santé.

Les données médicales complètes restent réservées aux acteurs explicitement
autorisés. Les autres modules ne consultent que les décisions opérationnelles.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.models import Acteur
from accounts.service import ControleAccesService
from affectations.models import AffectationCentre, CentreImmersion

from .models import RestrictionMedicale, VisiteMedicale


METHODE_VERS_ACTION = {
    "GET": "retrieve",
    "POST": "create",
    "PUT": "update",
    "PATCH": "partial_update",
    "DELETE": "destroy",
}


class PermissionSanteBase(BasePermission):
    message = "Permission FasoIM absente ou hors périmètre médical."
    action_permission_map = {}
    cible = ""

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
            **extraire_perimetre_sante(
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
            self.message = "Acteur non authentifié, inactif ou supprimé."
            return False

        if acteur.is_superuser:
            return True

        code = self.get_code_permission(request, view)
        if not code:
            return False

        resultat = ControleAccesService.acteur_peut(
            acteur,
            code,
            **extraire_perimetre_sante(
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
        action = getattr(view, "action", None)
        if action:
            return action
        if request.method.upper() == "GET":
            return (
                "retrieve"
                if getattr(view, "kwargs", {}).get("pk")
                else "list"
            )
        return METHODE_VERS_ACTION.get(request.method.upper())

    def get_code_permission(self, request, view):
        action = self.get_action(request, view)
        mapping = getattr(view, "action_permission_map", None)
        if mapping and action in mapping:
            return mapping[action]
        return self.action_permission_map.get(action)


class PermissionVisiteMedicale(PermissionSanteBase):
    cible = "visite"
    action_permission_map = {
        "list": "consulter_visites_medicales",
        "retrieve": "consulter_visites_medicales",
        "create": "saisir_resultat_visite_medicale",
        "brouillon": "saisir_resultat_visite_medicale",
        "contre_visite": "corriger_resultat_visite_medicale",
        "reappliquer": "appliquer_resultat_visite_medicale",
        "destroy": "annuler_visite_medicale",
        "annuler": "annuler_visite_medicale",
        "candidats": "consulter_candidats_visite_medicale",
        "prochaine": "consulter_candidats_visite_medicale",
        "statistiques": "consulter_statistiques_sante",
    }


class PermissionRestrictionMedicale(PermissionSanteBase):
    cible = "restriction"
    action_permission_map = {
        "list": "consulter_restrictions_medicales",
        "retrieve": "consulter_restrictions_medicales",
        "create": "enregistrer_restriction_medicale",
        "update": "modifier_restriction_medicale",
        "partial_update": "modifier_restriction_medicale",
        "destroy": "annuler_restriction_medicale",
        "lever": "lever_restriction_medicale",
    }


class PermissionImpactMedical(PermissionSanteBase):
    cible = "impact"
    action_permission_map = {
        "retrieve": "consulter_impacts_medicaux",
    }


def _entier_ou_none(valeur):
    try:
        return int(valeur) if valeur not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _premiere(source, *noms):
    for nom in noms:
        valeur = source.get(nom)
        if valeur not in (None, ""):
            return valeur
    return None


def contexte_objet(obj):
    if isinstance(obj, VisiteMedicale):
        return obj.session_id, obj.centre_id

    if isinstance(obj, RestrictionMedicale):
        visite = obj.visite_medicale
        return visite.session_id, visite.centre_id

    if isinstance(obj, AffectationCentre):
        return obj.session_id, obj.centre_id

    return None, None


def contexte_affectation(affectation_centre_id):
    affectation_centre_id = _entier_ou_none(
        affectation_centre_id
    )
    if not affectation_centre_id:
        return None, None

    affectation = AffectationCentre.objects.filter(
        id=affectation_centre_id,
        deleted_at__isnull=True,
    ).first()

    return contexte_objet(affectation) if affectation else (None, None)


def contexte_pk(cible, pk):
    pk = _entier_ou_none(pk)
    if pk is None:
        return None, None

    if cible == "impact":
        return contexte_affectation(pk)

    if cible == "visite":
        objet = (
            VisiteMedicale.objects.filter(
                id=pk,
                deleted_at__isnull=True,
            )
            .only("session_id", "centre_id")
            .first()
        )
        return contexte_objet(objet) if objet else (None, None)

    if cible == "restriction":
        objet = (
            RestrictionMedicale.objects.select_related(
                "visite_medicale"
            )
            .filter(
                id=pk,
                deleted_at__isnull=True,
            )
            .first()
        )
        return contexte_objet(objet) if objet else (None, None)

    return None, None


def extraire_perimetre_sante(
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

    elif kwargs.get("pk"):
        session_objet, centre_objet = contexte_pk(
            cible,
            kwargs["pk"],
        )
        session_id = session_objet or session_id
        centre_id = centre_objet or centre_id

    affectation_centre_id = _entier_ou_none(
        _premiere(
            data,
            "affectation_centre_id",
        )
        or _premiere(
            query,
            "affectation_centre_id",
        )
    )

    if affectation_centre_id:
        session_affectation, centre_affectation = (
            contexte_affectation(affectation_centre_id)
        )
        session_id = session_affectation or session_id
        centre_id = centre_affectation or centre_id

    visite_medicale_id = _entier_ou_none(
        _premiere(data, "visite_medicale_id")
        or _premiere(query, "visite_medicale_id")
    )
    if visite_medicale_id:
        visite = VisiteMedicale.objects.filter(
            id=visite_medicale_id,
            deleted_at__isnull=True,
        ).only("session_id", "centre_id").first()
        if visite:
            session_id = visite.session_id or session_id
            centre_id = visite.centre_id or centre_id

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
