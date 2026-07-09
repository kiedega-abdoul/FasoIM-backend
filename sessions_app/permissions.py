"""Permissions DRF propres au module sessions_app.

Ce fichier controle uniquement les actions API sur les tables :
- sessions_immersion
- parametres_session

Il traduit les actions DRF en codes de permissions FasoIM, extrait le
perimetre session, puis delegue la decision finale a ControleAccesService.
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission

from accounts.models import Acteur
from accounts.service import ControleAccesService

from .models import ParametreSession, SessionImmersion


METHODE_VERS_ACTION = {
    "GET": "retrieve",
    "POST": "create",
    "PUT": "update",
    "PATCH": "partial_update",
    "DELETE": "destroy",
}


class PermissionSessionsBase(BasePermission):
    """Base des permissions DRF pour le module sessions_app."""

    message = "Permission FasoIM absente ou hors périmètre pour le module sessions."
    action_permission_map: dict[str, str | None] = {}

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not self._acteur_est_valide(user):
            self.message = "Acteur non authentifié, inactif, désactivé ou supprimé logiquement."
            return False

        # Le superuser sert au démarrage, avant le seed complet des droits.
        if user.is_superuser:
            return True

        code_permission = self.get_code_permission(request, view)
        if not code_permission:
            self.message = "Aucune permission FasoIM n'est configurée pour cette action sessions_app."
            return False

        perimetre = extraire_perimetre_session(request, view)
        resultat = ControleAccesService.acteur_peut(user, code_permission, **perimetre)
        if not resultat.autorise:
            self.message = resultat.motif or self.message
            return False

        return True

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)
        if not self._acteur_est_valide(user):
            self.message = "Acteur non authentifié, inactif, désactivé ou supprimé logiquement."
            return False

        if user.is_superuser:
            return True

        code_permission = self.get_code_permission(request, view)
        if not code_permission:
            self.message = "Aucune permission FasoIM n'est configurée pour cette action sessions_app."
            return False

        perimetre = extraire_perimetre_session(request, view, obj=obj)
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


class PermissionSessionImmersion(PermissionSessionsBase):
    """Controle les actions API sur sessions_immersion."""

    action_permission_map = {
        "list": "lister_sessions",
        "retrieve": "consulter_session",
        "create": "creer_session",
        "update": "modifier_session",
        "partial_update": "modifier_session",
        "destroy": "archiver_session",
        "parametres": "consulter_session",
        "ouvrir": "modifier_session",
        "mettre_en_preparation": "modifier_session",
        "demarrer": "modifier_session",
        "terminer": "cloturer_session",
        "archiver": "archiver_session",
        "ouvertes_inscription": "lister_sessions",
        "historique": "consulter_historique_sessions",
    }


class PermissionParametreSession(PermissionSessionsBase):
    """Controle les actions API sur parametres_session."""

    action_permission_map = {
        "list": "consulter_session",
        "retrieve": "consulter_session",
        "update": "modifier_parametres_session",
        "partial_update": "modifier_parametres_session",
        "destroy": "modifier_parametres_session",
        "historique": "consulter_historique_parametres_session",
    }


def extraire_perimetre_session(request, view=None, obj=None):
    """Extrait le perimetre session depuis la requete ou l'objet cible."""

    kwargs = getattr(view, "kwargs", {}) or {}
    query_params = getattr(request, "query_params", {}) or {}
    data = getattr(request, "data", {}) or {}

    session_id = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("session_id", "session", "pk"),
    )

    if obj is not None:
        if isinstance(obj, SessionImmersion):
            session_id = obj.id
        elif isinstance(obj, ParametreSession):
            session_id = obj.session_id
        else:
            session_id = session_id or valeur_objet(obj, "session_id")

    return {
        "session_id": convertir_entier_ou_none(session_id),
        "region_code": None,
        "centre_id": None,
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
    "PermissionSessionsBase",
    "PermissionSessionImmersion",
    "PermissionParametreSession",
    "extraire_perimetre_session",
]
