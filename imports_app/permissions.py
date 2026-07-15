"""Permissions DRF propres au module imports_app.

Ce fichier controle uniquement les actions API du module imports :
- imports officiels ;
- correspondances de colonnes ;
- lignes d'import ;
- erreurs d'import.

Il ne lit pas les fichiers, ne lance pas Celery et ne valide pas les donnees.
Il traduit l'action DRF en code de permission FasoIM, extrait le contexte de
l'import, puis delegue la decision finale a ControleAccesService.
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission

from accounts.models import Acteur
from accounts.service import ControleAccesService

from .models import (
    CorrespondanceColonneImport,
    ErreurImport,
    ImportOfficiel,
    LigneImport,
)


METHODE_VERS_ACTION = {
    "GET": "retrieve",
    "POST": "create",
    "PUT": "update",
    "PATCH": "partial_update",
    "DELETE": "destroy",
}


class PermissionImportsBase(BasePermission):
    """Base des permissions DRF pour le module imports_app."""

    message = "Permission FasoIM absente ou hors périmètre pour le module imports."
    action_permission_map: dict[str, str | None] = {}

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not self._acteur_est_valide(user):
            self.message = "Acteur non authentifié, inactif, désactivé ou supprimé logiquement."
            return False

        # Le superuser garde l'accès de démarrage avant l'association complète
        # des rôles et permissions métier.
        if user.is_superuser:
            return True

        code_permission = self.get_code_permission(request, view)
        if not code_permission:
            self.message = "Aucune permission FasoIM n'est configurée pour cette action imports_app."
            return False

        perimetre = extraire_perimetre_import(request, view)
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
            self.message = "Aucune permission FasoIM n'est configurée pour cette action imports_app."
            return False

        perimetre = extraire_perimetre_import(request, view, obj=obj)
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


class PermissionImportOfficiel(PermissionImportsBase):
    """Controle les actions API sur les imports officiels."""

    action_permission_map = {
        "list": "lister_imports_officiels",
        "retrieve": "consulter_import_officiel",
        "create": "creer_import_officiel",
        "update": "modifier_import_officiel",
        "partial_update": "modifier_import_officiel",
        "destroy": "supprimer_import_officiel",
        "champs_attendus": "consulter_champs_attendus_import",
        "progression": "consulter_progression_import",
        "relancer_lecture": "relancer_lecture_import",
        "valider_correspondance": "valider_correspondance_import",
        "valider_lignes": "valider_lignes_import",
        "confirmer": "confirmer_import_officiel",
        "annuler": "annuler_import_officiel",
        "supprimer_logiquement": "supprimer_import_officiel",
    }


class PermissionCorrespondanceColonneImport(PermissionImportsBase):
    """Controle les actions API sur les correspondances de colonnes."""

    action_permission_map = {
        "list": "consulter_correspondances_import",
        "retrieve": "consulter_correspondances_import",
        "create": "valider_correspondance_import",
        "update": "valider_correspondance_import",
        "partial_update": "valider_correspondance_import",
        "destroy": "valider_correspondance_import",
    }


class PermissionLigneImport(PermissionImportsBase):
    """Controle les actions API sur les lignes d'import."""

    action_permission_map = {
        "list": "consulter_lignes_import",
        "retrieve": "consulter_lignes_import",
        "update": "corriger_ligne_import",
        "partial_update": "corriger_ligne_import",
        "destroy": "ignorer_ligne_import",
        "corriger": "corriger_ligne_import",
        "ignorer": "ignorer_ligne_import",
        "ignorer_plusieurs": "ignorer_ligne_import",
        "reintegrer_plusieurs": "ignorer_ligne_import",
        "revalider": "corriger_ligne_import",
    }


class PermissionErreurImport(PermissionImportsBase):
    """Controle les actions API sur les erreurs d'import."""

    action_permission_map = {
        "list": "consulter_erreurs_import",
        "retrieve": "consulter_erreurs_import",
    }


def extraire_perimetre_import(request, view=None, obj=None):
    """Extrait le contexte session et le périmètre ciblé d'une requête import.

    La session reste un contexte limitatif. Le périmètre réel de l'acteur est
    toujours vérifié dans ControleAccesService via ses affectations actives.
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
    import_id = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("import_id", "import_officiel_id", "import_officiel", "pk"),
    )
    ligne_id = premiere_valeur(
        kwargs,
        query_params,
        data,
        noms=("ligne_id", "ligne_import_id", "ligne_import"),
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
        contexte_objet = contexte_depuis_objet(obj)
        session_id = contexte_objet.get("session_id") or session_id
        import_id = contexte_objet.get("import_id") or import_id
        ligne_id = contexte_objet.get("ligne_id") or ligne_id
        region_code = contexte_objet.get("region_code") or region_code
        centre_id = contexte_objet.get("centre_id") or centre_id

    session_id = convertir_entier_ou_none(session_id)
    import_id = convertir_entier_ou_none(import_id)
    ligne_id = convertir_entier_ou_none(ligne_id)
    centre_id = convertir_entier_ou_none(centre_id)

    if session_id is None and import_id is not None:
        session_id = session_id_depuis_import(import_id)

    if session_id is None and ligne_id is not None:
        session_id = session_id_depuis_ligne(ligne_id)

    return {
        "session_id": session_id,
        "region_code": normaliser_texte_ou_none(region_code),
        "centre_id": centre_id,
    }


def contexte_depuis_objet(obj):
    if isinstance(obj, ImportOfficiel):
        return {
            "session_id": obj.session_id,
            "import_id": obj.id,
        }

    if isinstance(obj, CorrespondanceColonneImport):
        return {
            "session_id": getattr(obj.import_officiel, "session_id", None),
            "import_id": obj.import_officiel_id,
        }

    if isinstance(obj, LigneImport):
        return {
            "session_id": getattr(obj.import_officiel, "session_id", None),
            "import_id": obj.import_officiel_id,
            "ligne_id": obj.id,
        }

    if isinstance(obj, ErreurImport):
        import_officiel = getattr(obj, "import_officiel", None)
        ligne_import = getattr(obj, "ligne_import", None)

        if import_officiel is not None:
            return {
                "session_id": getattr(import_officiel, "session_id", None),
                "import_id": obj.import_officiel_id,
            }

        if ligne_import is not None:
            return {
                "session_id": getattr(ligne_import.import_officiel, "session_id", None),
                "import_id": ligne_import.import_officiel_id,
                "ligne_id": obj.ligne_import_id,
            }

    return {
        "session_id": valeur_objet(obj, "session_id"),
        "region_code": valeur_objet(obj, "region_code"),
        "centre_id": valeur_objet(obj, "centre_id"),
    }


def session_id_depuis_import(import_id):
    return (
        ImportOfficiel.objects.filter(pk=import_id, deleted_at__isnull=True)
        .values_list("session_id", flat=True)
        .first()
    )


def session_id_depuis_ligne(ligne_id):
    ligne = (
        LigneImport.objects.filter(pk=ligne_id, deleted_at__isnull=True)
        .select_related("import_officiel")
        .only("id", "import_officiel__session_id")
        .first()
    )
    if ligne is None:
        return None
    return ligne.import_officiel.session_id


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


def normaliser_texte_ou_none(valeur):
    if valeur in (None, ""):
        return None
    return str(valeur).strip() or None


__all__ = [
    "PermissionImportsBase",
    "PermissionImportOfficiel",
    "PermissionCorrespondanceColonneImport",
    "PermissionLigneImport",
    "PermissionErreurImport",
    "extraire_perimetre_import",
]
