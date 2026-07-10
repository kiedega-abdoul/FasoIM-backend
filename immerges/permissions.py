from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission

from accounts.service import ControleAccesService


class PermissionImmergeBase(BasePermission):
    """Porte d'entrée DRF du module immerges.

    Ce fichier vérifie seulement les droits. Il ne crée pas les immergés,
    ne génère pas les codes FasoIM et ne lance pas Celery.
    """

    message = "Permission absente ou hors périmètre."
    action_permission_map: dict[str, str] = {}

    def has_permission(self, request, view):
        acteur = request.user

        if not acteur or not acteur.is_authenticated:
            return False

        if getattr(acteur, "deleted_at", None) is not None:
            return False

        if hasattr(acteur, "est_actif") and not acteur.est_actif:
            return False

        if getattr(acteur, "is_superuser", False):
            return True

        code_permission = self.action_permission_map.get(getattr(view, "action", None))
        if not code_permission:
            return False

        contexte = extraire_contexte_requete(request, view=view)

        return ControleAccesService.acteur_peut(
            acteur,
            code_permission,
            session_id=contexte.get("session_id"),
            region_code=contexte.get("region_code"),
            centre_id=contexte.get("centre_id"),
        )

    def has_object_permission(self, request, view, obj):
        acteur = request.user

        if getattr(acteur, "is_superuser", False):
            return True

        code_permission = self.action_permission_map.get(getattr(view, "action", None))
        if not code_permission:
            return False

        contexte = extraire_contexte_requete(request, view=view, obj=obj)

        return ControleAccesService.acteur_peut(
            acteur,
            code_permission,
            session_id=contexte.get("session_id"),
            region_code=contexte.get("region_code"),
            centre_id=contexte.get("centre_id"),
        )


class PermissionSourceImmerge(PermissionImmergeBase):
    """Permissions des sources : examens, concours et sélectionnés."""

    action_permission_map = {
        "list": "lister_sources_immerges",
        "retrieve": "consulter_source_immerge",
        "create": "creer_source_immerge",
        "update": "modifier_source_immerge",
        "partial_update": "modifier_source_immerge",
        "destroy": "supprimer_source_immerge",
        "centraliser": "centraliser_source_immerge",
        "centraliser_lot_async": "centraliser_sources_importees",
    }


class PermissionInscriptionVolontaire(PermissionImmergeBase):
    """Permissions des inscriptions volontaires."""

    action_permission_map = {
        "list": "lister_inscriptions_volontaires",
        "retrieve": "consulter_inscription_volontaire",
        "create": "creer_inscription_volontaire",
        "update": "modifier_inscription_volontaire",
        "partial_update": "modifier_inscription_volontaire",
        "destroy": "supprimer_inscription_volontaire",
        "accepter": "accepter_inscription_volontaire",
        "rejeter": "refuser_inscription_volontaire",
        "annuler": "annuler_inscription_volontaire",
        "accepter_lot_async": "accepter_inscriptions_volontaires_lot",
        "centraliser_acceptes_async": "centraliser_volontaires_acceptes",
    }


class PermissionImmergeCentral(PermissionImmergeBase):
    """Permissions de la table centrale Immerge."""

    action_permission_map = {
        "list": "lister_immerges",
        "retrieve": "consulter_immerge",
        "create": "centraliser_immerge",
        "update": "modifier_immerge",
        "partial_update": "modifier_immerge",
        "destroy": "supprimer_immerge",
        "centraliser": "centraliser_immerge",
        "centraliser_source_async": "centraliser_source_immerge",
        "changer_statut": "changer_statut_immerge",
        "changer_statut_lot_async": "changer_statut_immerges_lot",
        "generer_code": "generer_code_immerge",
        "generer_codes_manquants_async": "generer_codes_immerges",
        "regenerer_qr_codes_async": "regenerer_qr_immerges",
        "supprimer_immerges_session_async": "supprimer_immerges_session",
        "progression": "consulter_progression_immerges",
        "stats": "consulter_statistiques_immerges",
        "confirmer_import_async": "confirmer_import_vers_immerges",
    }


def extraire_contexte_requete(request, *, view=None, obj=None):
    """Extrait session/région/centre pour le contrôle d'accès."""

    session_id = premiere_valeur(
        request.data,
        request.query_params,
        noms=("session", "session_id"),
    )
    region_code = premiere_valeur(
        request.data,
        request.query_params,
        noms=("region_code", "region", "region_id"),
    )
    centre_id = premiere_valeur(
        request.data,
        request.query_params,
        noms=("centre_id", "centre"),
    )

    if obj is not None:
        session_id = session_id or valeur_objet(obj, "session_id")
        region_code = region_code or valeur_objet(obj, "region_code")
        centre_id = centre_id or valeur_objet(obj, "centre_id")

        import_officiel = getattr(obj, "import_officiel", None)
        if import_officiel is not None:
            session_id = session_id or getattr(import_officiel, "session_id", None)

    if not session_id:
        import_officiel_id = premiere_valeur(
            request.data,
            request.query_params,
            noms=("import_officiel", "import_officiel_id"),
        )
        session_id = session_depuis_import_officiel(import_officiel_id)

    return {
        "session_id": convertir_entier_ou_none(session_id),
        "region_code": region_code or None,
        "centre_id": convertir_entier_ou_none(centre_id),
    }


def session_depuis_import_officiel(import_officiel_id):
    if not import_officiel_id:
        return None

    try:
        from imports_app.models import ImportOfficiel

        import_officiel = ImportOfficiel.objects.only("session_id").get(id=import_officiel_id)
        return import_officiel.session_id
    except Exception:
        return None


def premiere_valeur(*sources: Any, noms: tuple[str, ...]):
    for source in sources:
        if not source:
            continue
        for nom in noms:
            try:
                valeur = source.get(nom)
            except AttributeError:
                valeur = getattr(source, nom, None)
            if valeur not in (None, ""):
                return valeur
    return None


def valeur_objet(obj, nom):
    if hasattr(obj, nom):
        valeur = getattr(obj, nom)
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
