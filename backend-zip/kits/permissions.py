"""Permissions DRF du module kits."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.models import Acteur
from accounts.service import ControleAccesService
from affectations.models import AffectationCentre, CentreImmersion

from .models import ArticleKit, RemiseKit


class PermissionKitsBase(BasePermission):
    message = "Permission kits absente ou hors périmètre."
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
            self.message = (
                "Aucune permission n'est configurée pour cette action."
            )
            return False

        resultat = ControleAccesService.acteur_peut(
            acteur,
            code,
            **extraire_perimetre_kits(
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
            **extraire_perimetre_kits(
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
        return None

    def get_code_permission(self, request, view):
        action = self.get_action(request, view)
        mapping = getattr(view, "action_permission_map", None)
        if mapping and action in mapping:
            return mapping[action]
        return self.action_permission_map.get(action)


class PermissionArticleKit(PermissionKitsBase):
    cible = "article"
    action_permission_map = {
        "list": "consulter_articles_kit",
        "retrieve": "consulter_articles_kit",
        "applicables": "consulter_articles_kit",
        "create": "creer_article_kit_a_apporter",
        "update": "modifier_article_kit",
        "partial_update": "modifier_article_kit",
        "destroy": "supprimer_article_kit",
        "desactiver": "desactiver_article_kit",
        "reactiver": "reactiver_article_kit",
    }

    def get_code_permission(self, request, view):
        action = self.get_action(request, view)
        if action == "create":
            type_kit = getattr(request, "data", {}).get("type_kit")
            if type_kit == ArticleKit.TypeKit.A_REMETTRE:
                return "creer_article_kit_a_remettre"
            return "creer_article_kit_a_apporter"
        return super().get_code_permission(request, view)


class PermissionRemiseKit(PermissionKitsBase):
    cible = "remise"
    action_permission_map = {
        "list": "consulter_remises_kit",
        "retrieve": "consulter_remises_kit",
        "create": "enregistrer_remise_kit",
        "preparer_individuelle": "enregistrer_remise_kit",
        "valider_complete": "enregistrer_remise_kit",
        "remplacer": "enregistrer_remise_kit",
        "dispenser": "enregistrer_remise_kit",
        "destroy": "annuler_remise_kit",
        "statut_global": "consulter_remises_kit",
        "statistiques": "consulter_statistiques_kits",
    }


class PermissionOperationKits(PermissionKitsBase):
    cible = "operation"
    action_permission_map = {
        "retrieve": "consulter_progression_kits",
        "preparer_masse": "preparer_remises_kit_masse",
        "valider_masse": "valider_remises_kit_masse",
        "annuler_masse": "annuler_remises_kit_masse",
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
    if isinstance(obj, ArticleKit):
        return obj.session_id, obj.centre_id

    if isinstance(obj, RemiseKit):
        affectation = obj.affectation_centre
        return affectation.session_id, affectation.centre_id

    if isinstance(obj, AffectationCentre):
        return obj.session_id, obj.centre_id

    return None, None


def contexte_article(article_id):
    article_id = _entier_ou_none(article_id)
    if not article_id:
        return None, None

    article = ArticleKit.objects.filter(
        id=article_id,
        deleted_at__isnull=True,
    ).only("session_id", "centre_id").first()

    return contexte_objet(article) if article else (None, None)


def contexte_affectation(affectation_centre_id):
    affectation_centre_id = _entier_ou_none(
        affectation_centre_id
    )
    if not affectation_centre_id:
        return None, None

    affectation = AffectationCentre.objects.filter(
        id=affectation_centre_id,
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

    if cible == "article":
        return contexte_article(pk)

    if cible == "remise":
        remise = (
            RemiseKit.objects.select_related(
                "affectation_centre"
            )
            .filter(
                id=pk,
                deleted_at__isnull=True,
            )
            .first()
        )
        return contexte_objet(remise) if remise else (None, None)

    return None, None


def extraire_perimetre_kits(
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

    article_id = _entier_ou_none(
        _premiere(data, "article_kit_id")
        or _premiere(query, "article_kit_id")
    )
    if article_id:
        session_article, centre_article = contexte_article(
            article_id
        )
        session_id = session_article or session_id
        centre_id = centre_article or centre_id

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
