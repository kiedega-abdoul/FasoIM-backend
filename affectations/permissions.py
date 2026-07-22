"""Permissions DRF propres au module affectations.

Ce fichier contrôle les régions, centres, affectations régionales et
affectations aux centres. Il ne choisit aucune destination, ne calcule aucune
capacité et ne lance aucune tâche Celery. Il traduit seulement l'action API en
code de permission FasoIM, extrait le périmètre puis délègue la décision à
ControleAccesService.
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission

from accounts.access_context import obtenir_affectation_courante_id
from accounts.models import Acteur, AffectationActeur
from accounts.service import ControleAccesService

from .models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)


METHODE_VERS_ACTION = {
    "GET": "retrieve",
    "POST": "create",
    "PUT": "update",
    "PATCH": "partial_update",
    "DELETE": "destroy",
}


class PermissionAffectationsBase(BasePermission):
    """Base commune des permissions du module affectations."""

    message = "Permission FasoIM absente ou hors périmètre pour les affectations."
    action_permission_map: dict[str, str | None] = {}
    cible = ""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not self._acteur_est_valide(user):
            self.message = (
                "Acteur non authentifié, inactif, désactivé "
                "ou supprimé logiquement."
            )
            return False

        if user.is_superuser:
            return True

        code_permission = self.get_code_permission(request, view)
        if not code_permission:
            self.message = (
                "Aucune permission FasoIM n'est configurée pour cette "
                "action du module affectations."
            )
            return False

        perimetre = extraire_perimetre_affectation(
            request,
            view,
            cible=self.cible,
        )
        resultat = ControleAccesService.acteur_peut(
            user,
            code_permission,
            **perimetre,
        )
        if not resultat.autorise:
            self.message = resultat.motif or self.message
            return False
        return True

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)
        if not self._acteur_est_valide(user):
            self.message = (
                "Acteur non authentifié, inactif, désactivé "
                "ou supprimé logiquement."
            )
            return False

        if user.is_superuser:
            return True

        code_permission = self.get_code_permission(request, view)
        if not code_permission:
            self.message = (
                "Aucune permission FasoIM n'est configurée pour cette "
                "action du module affectations."
            )
            return False

        perimetre = extraire_perimetre_affectation(
            request,
            view,
            obj=obj,
            cible=self.cible,
        )
        resultat = ControleAccesService.acteur_peut(
            user,
            code_permission,
            **perimetre,
        )
        if not resultat.autorise:
            self.message = resultat.motif or self.message
            return False
        return True

    @staticmethod
    def _acteur_est_valide(user):
        return bool(
            user
            and user.is_authenticated
            and isinstance(user, Acteur)
            and user.is_active
            and user.statut == Acteur.Statut.ACTIF
            and user.deleted_at is None
        )

    def get_action(self, request, view):
        action = getattr(view, "action", None)
        if action:
            return action

        methode = request.method.upper()
        action = METHODE_VERS_ACTION.get(methode)

        if methode == "GET":
            kwargs = getattr(view, "kwargs", {}) or {}
            action = "retrieve" if kwargs.get("pk") else "list"

        return action

    def get_code_permission(self, request, view):
        action = self.get_action(request, view)

        mapping_vue = getattr(view, "action_permission_map", None)
        if mapping_vue and action in mapping_vue:
            return mapping_vue[action]

        permission_code = getattr(view, "permission_code", None)
        if permission_code:
            return permission_code

        return self.action_permission_map.get(action)


class PermissionRegionImmersion(PermissionAffectationsBase):
    cible = "region"
    action_permission_map = {
        "list": "lister_regions",
        "retrieve": "consulter_region",
        "create": "creer_region",
        "update": "modifier_region",
        "partial_update": "modifier_region",
        "destroy": "desactiver_region",
        "desactiver": "desactiver_region",
        "reactiver": "modifier_region",
    }


class PermissionCentreImmersion(PermissionAffectationsBase):
    cible = "centre"
    action_permission_map = {
        "list": "lister_centres",
        "retrieve": "consulter_centre",
        "create": "creer_centre",
        "update": "modifier_centre",
        "partial_update": "modifier_centre",
        "destroy": "desactiver_centre",
        "desactiver": "desactiver_centre",
        "mettre_en_maintenance": "mettre_centre_maintenance",
        "reactiver": "reactiver_centre",
        "verifier_capacite": "verifier_capacite_centre",
    }


class PermissionAffectationRegionale(PermissionAffectationsBase):
    cible = "affectation_regionale"
    action_permission_map = {
        "list": "consulter_affectations_regionales",
        "retrieve": "consulter_affectations_regionales",
        "create": "affecter_region",
        "update": "modifier_affectation_regionale",
        "partial_update": "modifier_affectation_regionale",
        "destroy": "annuler_affectation_regionale",
        "proposer_lot": "proposer_affectation_regionale",
        "progression": "consulter_affectations_regionales",
        "affecter_manuellement": "affecter_region",
        "valider_lot": "valider_affectation_regionale",
        "rejeter_lot": "modifier_affectation_regionale",
        "annuler": "annuler_affectation_regionale",
        "transferer": "modifier_affectation_regionale",
        "historique": "consulter_affectations_regionales",
        "capacites": "consulter_affectations_regionales",
    }


class PermissionAffectationCentre(PermissionAffectationsBase):
    cible = "affectation_centre"
    action_permission_map = {
        "list": "consulter_affectations_centres",
        "retrieve": "consulter_affectations_centres",
        "create": "affecter_centre",
        "update": "modifier_affectation_centre",
        "partial_update": "modifier_affectation_centre",
        "destroy": "annuler_affectation_centre",
        "proposer_lot": "proposer_affectation_centre",
        "progression": "consulter_affectations_centres",
        "affecter_manuellement": "affecter_centre",
        "valider_lot": "valider_affectation_centre",
        "rejeter_lot": "modifier_affectation_centre",
        "annuler": "annuler_affectation_centre",
        "transferer": "modifier_affectation_centre",
        "verifier_compatibilite": "verifier_compatibilite_centre",
        "historique": "consulter_affectations_centres",
        "capacites": "consulter_affectations_centres",
        "verifier_capacite": "verifier_capacite_centre",
        "statistiques_centre": "consulter_affectations_centres",
    }


def extraire_perimetre_affectation(
    request,
    view=None,
    obj=None,
    *,
    cible: str = "",
):
    """Extrait session, région et centre sans prendre de décision métier."""

    kwargs = getattr(view, "kwargs", {}) or {}
    query_params = getattr(request, "query_params", {}) or {}
    data = getattr(request, "data", {}) or {}

    session_id = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("session_id", "session"),
    )
    region_id = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("region_id",),
    )
    region_code = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("region_code",),
    )
    centre_id = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("centre_id", "centre"),
    )
    pk = premiere_valeur(kwargs, noms=("pk",))

    if obj is not None:
        contexte = contexte_depuis_objet(obj)
        session_id = contexte.get("session_id") or session_id
        region_id = contexte.get("region_id") or region_id
        region_code = contexte.get("region_code") or region_code
        centre_id = contexte.get("centre_id") or centre_id
    elif pk is not None:
        contexte = contexte_depuis_pk(cible, pk)
        session_id = contexte.get("session_id") or session_id
        region_id = contexte.get("region_id") or region_id
        region_code = contexte.get("region_code") or region_code
        centre_id = contexte.get("centre_id") or centre_id

    session_id = convertir_entier_ou_none(session_id)
    region_id = convertir_entier_ou_none(region_id)
    centre_id = convertir_entier_ou_none(centre_id)

    if centre_id is not None:
        contexte_centre = contexte_depuis_centre_id(centre_id)
        region_id = contexte_centre.get("region_id") or region_id
        region_code = contexte_centre.get("region_code") or region_code

    if region_code in (None, "") and region_id is not None:
        region_code = region_code_depuis_id(region_id)

    contexte_courant = contexte_depuis_affectation_courante(request)
    if session_id is None:
        session_id = contexte_courant.get("session_id") or session_id

    if region_code in (None, "") and centre_id is None:
        session_id = contexte_courant.get("session_id") or session_id
        region_code = contexte_courant.get("region_code") or region_code
        centre_id = contexte_courant.get("centre_id") or centre_id

    return {
        "session_id": session_id,
        "region_code": normaliser_texte_ou_none(region_code),
        "centre_id": centre_id,
    }


def contexte_depuis_affectation_courante(request=None) -> dict:
    affectation_id = convertir_entier_ou_none(obtenir_affectation_courante_id())
    if affectation_id is None:
        return {}

    queryset = AffectationActeur.objects.filter(
        id=affectation_id,
        statut=AffectationActeur.Statut.ACTIVE,
        deleted_at__isnull=True,
    )
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        queryset = queryset.filter(acteur_id=user.id)

    affectation = queryset.only(
        "id",
        "acteur_id",
        "session_id",
        "niveau_affectation",
        "region_code",
        "centre_id",
    ).first()
    if affectation is None:
        return {}

    contexte = {}
    if affectation.session_id:
        contexte["session_id"] = affectation.session_id
    if affectation.niveau_affectation == AffectationActeur.NiveauAffectation.REGION:
        contexte["region_code"] = affectation.region_code
    if affectation.niveau_affectation == AffectationActeur.NiveauAffectation.CENTRE:
        contexte["centre_id"] = affectation.centre_id
        if affectation.region_code:
            contexte["region_code"] = affectation.region_code
    return contexte


def contexte_depuis_objet(obj) -> dict:
    if isinstance(obj, RegionImmersion):
        return {
            "region_id": obj.id,
            "region_code": obj.code,
        }

    if isinstance(obj, CentreImmersion):
        return {
            "region_id": obj.region_id,
            "region_code": getattr(obj.region, "code", None),
            "centre_id": obj.id,
        }

    if isinstance(obj, AffectationRegionale):
        return {
            "session_id": obj.session_id,
            "region_id": obj.region_id,
            "region_code": getattr(obj.region, "code", None),
        }

    if isinstance(obj, AffectationCentre):
        return {
            "session_id": obj.session_id,
            "region_id": getattr(obj.centre, "region_id", None),
            "region_code": getattr(
                getattr(obj.centre, "region", None),
                "code",
                None,
            ),
            "centre_id": obj.centre_id,
        }

    return {
        "session_id": valeur_objet(obj, "session_id"),
        "region_id": valeur_objet(obj, "region_id"),
        "region_code": valeur_objet(obj, "region_code"),
        "centre_id": valeur_objet(obj, "centre_id"),
    }


def contexte_depuis_pk(cible: str, pk) -> dict:
    identifiant = convertir_entier_ou_none(pk)
    if identifiant is None:
        return {}

    if cible == "region":
        region = (
            RegionImmersion.objects.filter(
                pk=identifiant,
                deleted_at__isnull=True,
            )
            .values("id", "code")
            .first()
        )
        if region:
            return {
                "region_id": region["id"],
                "region_code": region["code"],
            }

    if cible == "centre":
        return contexte_depuis_centre_id(identifiant)

    if cible == "affectation_regionale":
        ligne = (
            AffectationRegionale.objects.filter(
                pk=identifiant,
                deleted_at__isnull=True,
            )
            .select_related("region")
            .only("id", "session_id", "region_id", "region__code")
            .first()
        )
        if ligne:
            return {
                "session_id": ligne.session_id,
                "region_id": ligne.region_id,
                "region_code": ligne.region.code,
            }

    if cible == "affectation_centre":
        ligne = (
            AffectationCentre.objects.filter(
                pk=identifiant,
                deleted_at__isnull=True,
            )
            .select_related("centre__region")
            .only(
                "id",
                "session_id",
                "centre_id",
                "centre__region_id",
                "centre__region__code",
            )
            .first()
        )
        if ligne:
            return {
                "session_id": ligne.session_id,
                "region_id": ligne.centre.region_id,
                "region_code": ligne.centre.region.code,
                "centre_id": ligne.centre_id,
            }

    return {}


def contexte_depuis_centre_id(centre_id: int) -> dict:
    centre = (
        CentreImmersion.objects.filter(
            pk=centre_id,
            deleted_at__isnull=True,
        )
        .select_related("region")
        .only("id", "region_id", "region__code")
        .first()
    )
    if centre is None:
        return {}
    return {
        "region_id": centre.region_id,
        "region_code": centre.region.code,
        "centre_id": centre.id,
    }


def region_code_depuis_id(region_id: int):
    return (
        RegionImmersion.objects.filter(
            pk=region_id,
            deleted_at__isnull=True,
        )
        .values_list("code", flat=True)
        .first()
    )


def premiere_valeur(*sources: Any, noms: tuple[str, ...]):
    for source in sources:
        for nom in noms:
            valeur = lire_source(source, nom)
            if valeur not in (None, ""):
                return valeur
    return None


def lire_source(source, nom):
    if not source:
        return None
    try:
        return source.get(nom)
    except AttributeError:
        return None


def valeur_objet(obj, nom):
    valeur = getattr(obj, nom, None)
    if valeur not in (None, ""):
        return valeur
    return None


def convertir_entier_ou_none(valeur):
    if valeur in (None, ""):
        return None
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


def normaliser_texte_ou_none(valeur):
    if valeur in (None, ""):
        return None
    return str(valeur).strip() or None


__all__ = [
    "PermissionAffectationsBase",
    "PermissionRegionImmersion",
    "PermissionCentreImmersion",
    "PermissionAffectationRegionale",
    "PermissionAffectationCentre",
    "extraire_perimetre_affectation",
]
