"""Permissions DRF propres au module accounts.

Ce fichier ne contient pas le catalogue des permissions métier.
Le catalogue est dans la table accounts.Permission.

Ici, on traduit les actions API sur les tables accounts en codes de
permissions FasoIM, puis on délègue le contrôle réel à ControleAccesService.
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission

from .models import Acteur
from .service import ControleAccesService


METHODE_VERS_ACTION = {
    "GET": "retrieve",
    "POST": "create",
    "PUT": "update",
    "PATCH": "partial_update",
    "DELETE": "destroy",
}


class EstActeurActif(BasePermission):
    """Autorise uniquement les acteurs internes authentifiés et actifs."""

    message = "Acteur non authentifié, inactif, suspendu, désactivé ou supprimé logiquement."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and isinstance(user, Acteur)
            and user.is_active
            and user.statut == Acteur.Statut.ACTIF
            and user.deleted_at is None
        )


class PermissionAccountsBase(BasePermission):
    """Base des permissions DRF pour les tables du module accounts.

    Une sous-classe définit action_permission_map. La classe traduit l'action
    DRF en code permission FasoIM, extrait le périmètre de la requête, puis
    appelle ControleAccesService.
    """

    message = "Permission FasoIM absente ou hors périmètre."
    action_permission_map: dict[str, str | None] = {}

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not self._acteur_est_valide(user):
            self.message = EstActeurActif.message
            return False

        # Le superuser sert au démarrage du système avant le seed complet
        # des rôles, permissions et affectations.
        if user.is_superuser:
            return True

        code_permission = self.get_code_permission(request, view)
        if not code_permission:
            self.message = "Aucune permission FasoIM n'est configurée pour cette action accounts."
            return False

        perimetre = extraire_perimetre_requete(request, view)
        resultat = ControleAccesService.acteur_peut(user, code_permission, **perimetre)
        if not resultat.autorise:
            self.message = resultat.motif or self.message
            return False

        return True

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)
        if not self._acteur_est_valide(user):
            self.message = EstActeurActif.message
            return False

        if user.is_superuser:
            return True

        code_permission = self.get_code_permission(request, view)
        if not code_permission:
            self.message = "Aucune permission FasoIM n'est configurée pour cette action accounts."
            return False

        perimetre = extraire_perimetre_requete(request, view, obj=obj)
        resultat = ControleAccesService.acteur_peut(user, code_permission, **perimetre)
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

        # Sur un APIView simple, GET peut être une liste ou un détail.
        # Si pk est présent, on considère retrieve, sinon list.
        if methode == "GET":
            kwargs = getattr(view, "kwargs", {}) or {}
            action = "retrieve" if kwargs.get("pk") else "list"

        return action

    def get_code_permission(self, request, view):
        action = self.get_action(request, view)

        # La vue peut surcharger le mapping de l'application.
        mapping_vue = getattr(view, "action_permission_map", None)
        if mapping_vue and action in mapping_vue:
            return mapping_vue[action]

        permission_code = getattr(view, "permission_code", None)
        if permission_code:
            return permission_code

        return self.action_permission_map.get(action)


class PeutVoirSonProfilOuPermissionActeur(PermissionAccountsBase):
    """Autorise son propre profil, sinon exige consulter/modifier_acteur."""

    action_permission_map = {
        "retrieve": "consulter_acteur",
        "update": "modifier_acteur",
        "partial_update": "modifier_acteur",
    }

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)
        if not self._acteur_est_valide(user):
            self.message = EstActeurActif.message
            return False

        if user.is_superuser:
            return True

        # Un acteur peut consulter ou modifier son propre profil à travers
        # les endpoints dédiés au profil, sans droit de gestion des autres.
        if isinstance(obj, Acteur) and obj.id == user.id:
            return True

        return super().has_object_permission(request, view, obj)


class PermissionActeur(PermissionAccountsBase):
    """Contrôle les actions API sur la table acteurs."""

    action_permission_map = {
        "list": "lister_acteurs",
        "retrieve": "consulter_acteur",
        "create": "creer_acteur",
        "update": "modifier_acteur",
        "partial_update": "modifier_acteur",
        "destroy": "desactiver_acteur",
        "desactiver": "desactiver_acteur",
        "reactiver": "reactiver_acteur",
        "changer_mot_de_passe": "changer_mot_de_passe",
    }


class PermissionRole(PermissionAccountsBase):
    """Contrôle les actions API sur la table roles."""

    action_permission_map = {
        "list": "lister_roles",
        "retrieve": "consulter_role",
        "create": "creer_role",
        "update": "modifier_role",
        "partial_update": "modifier_role",
        "destroy": "desactiver_role",
        "desactiver": "desactiver_role",
    }


class PermissionPermissionSysteme(PermissionAccountsBase):
    """Contrôle les actions API sur la table permissions.

    Les créations/modifications/suppressions de permissions système sont
    volontairement réservées au superuser tant que le seed officiel n'est pas
    défini. Les acteurs métier peuvent seulement lister ou consulter le
    catalogue existant s'ils ont les permissions correspondantes.
    """

    action_permission_map = {
        "list": "lister_permissions",
        "retrieve": "consulter_permission",
        "create": None,
        "update": None,
        "partial_update": None,
        "destroy": None,
    }


class PermissionRolePermission(PermissionAccountsBase):
    """Contrôle les actions API sur role_permissions."""

    action_permission_map = {
        "list": "consulter_role",
        "retrieve": "consulter_role",
        "create": "ajouter_permission_role",
        "destroy": "retirer_permission_role",
        "retirer": "retirer_permission_role",
    }


class PermissionAffectationActeur(PermissionAccountsBase):
    """Contrôle les actions API sur affectations_acteurs."""

    action_permission_map = {
        "list": "lister_acteurs",
        "retrieve": "consulter_acteur",
        "create": "affecter_acteur_session",
        "references": "affecter_acteur_session",
        "update": "suspendre_affectation_acteur",
        "partial_update": "suspendre_affectation_acteur",
        "destroy": "retirer_affectation_acteur",
        "suspendre": "suspendre_affectation_acteur",
        "reactiver": "reactiver_affectation_acteur",
        "retirer": "retirer_affectation_acteur",
    }


class PermissionAffectationRole(PermissionAccountsBase):
    """Contrôle les actions API sur affectation_roles."""

    action_permission_map = {
        "list": "consulter_acteur",
        "retrieve": "consulter_acteur",
        "create": "attribuer_role",
        "destroy": "retirer_role",
        "retirer": "retirer_role",
    }


class PermissionAffectationPermission(PermissionAccountsBase):
    """Contrôle les permissions directes exceptionnelles."""

    action_permission_map = {
        "list": "consulter_permission",
        "retrieve": "consulter_permission",
        "create": "attribuer_permission_directe",
        "destroy": "retirer_permission_directe",
        "retirer": "retirer_permission_directe",
        "deleguer": "deleguer_permission",
    }


class PermissionDemandePermission(PermissionAccountsBase):
    """Contrôle les actions API sur demandes_permissions."""

    action_permission_map = {
        "list": "lister_demandes_permissions",
        "retrieve": "consulter_demande_permission",
        "create": "demander_permission",
        "destroy": "annuler_demande_permission",
        "approuver": "approuver_demande_permission",
        "refuser": "refuser_demande_permission",
        "annuler": "annuler_demande_permission",
    }


class PermissionDelegationActeur(PermissionAccountsBase):
    """Contrôle les actions API sur delegations_acteurs."""

    action_permission_map = {
        "list": "lister_delegations",
        "retrieve": "consulter_delegation",
        "create": "creer_delegation",
        "update": "modifier_delegation",
        "partial_update": "modifier_delegation",
        "destroy": "annuler_delegation",
        "terminer": "terminer_delegation",
        "annuler": "annuler_delegation",
    }


def extraire_perimetre_requete(request, view=None, obj=None):
    """Extrait session_id, region_code et centre_id pour le contrôle d'accès.

    Les valeurs peuvent venir de l'URL, des query params, du body ou de l'objet
    contrôlé. Cela permet aux permissions de chaque application de rester
    légères et de déléguer le vrai contrôle au service central.
    """

    kwargs = getattr(view, "kwargs", {}) or {}
    query_params = getattr(request, "query_params", {}) or {}
    data = getattr(request, "data", {}) or {}

    session_id = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("session_id", "session"),
    )
    region_code = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("region_code", "region"),
    )
    centre_id = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("centre_id", "centre"),
    )

    if obj is not None:
        session_id = session_id or valeur_objet(obj, "session_id")
        region_code = region_code or valeur_objet(obj, "region_code")
        centre_id = centre_id or valeur_objet(obj, "centre_id")

        affectation = getattr(obj, "affectation_acteur", None)
        if affectation is not None:
            session_id = session_id or valeur_objet(affectation, "session_id")
            region_code = region_code or valeur_objet(affectation, "region_code")
            centre_id = centre_id or valeur_objet(affectation, "centre_id")

    return {
        "session_id": convertir_entier_ou_none(session_id),
        "region_code": str(region_code).strip() if region_code not in (None, "") else None,
        "centre_id": convertir_entier_ou_none(centre_id),
    }


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

    # Pour un ForeignKey session, Django garde aussi session_id.
    if nom == "session_id" and getattr(obj, "session", None) is not None:
        return getattr(obj.session, "id", None)

    return None


def convertir_entier_ou_none(valeur):
    if valeur in (None, ""):
        return None
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


__all__ = [
    "EstActeurActif",
    "PermissionAccountsBase",
    "PeutVoirSonProfilOuPermissionActeur",
    "PermissionActeur",
    "PermissionRole",
    "PermissionPermissionSysteme",
    "PermissionRolePermission",
    "PermissionAffectationActeur",
    "PermissionAffectationRole",
    "PermissionAffectationPermission",
    "PermissionDemandePermission",
    "PermissionDelegationActeur",
    "extraire_perimetre_requete",
]
