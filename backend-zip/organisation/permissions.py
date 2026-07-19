"""Permissions DRF du module organisation interne."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.access_context import obtenir_affectation_courante_id
from accounts.models import Acteur
from accounts.models import AffectationActeur
from accounts.service import ControleAccesService

from .models import (
    AffectationGroupe,
    AttributionLit,
    Dortoir,
    Groupe,
    Lit,
    RegleOrganisationCentre,
    Section,
)


METHODE_VERS_ACTION = {
    "GET": "retrieve",
    "POST": "create",
    "PUT": "update",
    "PATCH": "partial_update",
    "DELETE": "destroy",
}


class PermissionOrganisationBase(BasePermission):
    message = "Permission FasoIM absente ou hors périmètre."
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
            **extraire_perimetre_organisation(
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
            **extraire_perimetre_organisation(
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
            return "retrieve" if getattr(view, "kwargs", {}).get("pk") else "list"
        return METHODE_VERS_ACTION.get(request.method.upper())

    def get_code_permission(self, request, view):
        action = self.get_action(request, view)
        mapping = getattr(view, "action_permission_map", None)
        if mapping and action in mapping:
            return mapping[action]
        return self.action_permission_map.get(action)


class PermissionRegleOrganisation(PermissionOrganisationBase):
    cible = "regle"
    action_permission_map = {
        "list": "consulter_regles_centre",
        "retrieve": "consulter_regles_centre",
        "create": "configurer_regles_centre",
        "update": "modifier_regles_centre",
        "partial_update": "modifier_regles_centre",
        "destroy": "modifier_regles_centre",
        "generer_structures": "generer_sections_groupes",
        "valider_organisation": "valider_organisation_interne",
        "marquer_prete_publication": "marquer_centre_pret_publication",
        "synthese": "consulter_regles_centre",
        "progression": "consulter_regles_centre",
    }


class PermissionSection(PermissionOrganisationBase):
    cible = "section"
    action_permission_map = {
        "list": "consulter_regles_centre",
        "retrieve": "consulter_regles_centre",
        "create": "creer_section",
        "update": "modifier_section",
        "partial_update": "modifier_section",
        "destroy": "supprimer_section",
    }


class PermissionGroupe(PermissionOrganisationBase):
    cible = "groupe"
    action_permission_map = {
        "list": "consulter_regles_centre",
        "retrieve": "consulter_regles_centre",
        "create": "creer_groupe",
        "update": "modifier_groupe",
        "partial_update": "modifier_groupe",
        "destroy": "supprimer_groupe",
    }


class PermissionAffectationGroupe(PermissionOrganisationBase):
    cible = "affectation_groupe"
    action_permission_map = {
        "list": "consulter_regles_centre",
        "retrieve": "consulter_regles_centre",
        "create": "affecter_immerge_groupe",
        "affecter_manuellement": "affecter_immerge_groupe",
        "proposer_lot": "affecter_immerge_groupe",
        "valider_lot": "affecter_immerge_groupe",
        "rejeter_lot": "affecter_immerge_groupe",
        "destroy": "retirer_immerge_groupe",
        "retirer": "retirer_immerge_groupe",
        "progression": "consulter_regles_centre",
    }


class PermissionDortoir(PermissionOrganisationBase):
    cible = "dortoir"
    action_permission_map = {
        "list": "consulter_hebergement",
        "retrieve": "consulter_hebergement",
        "create": "creer_dortoir",
        "update": "modifier_dortoir",
        "partial_update": "modifier_dortoir",
        "destroy": "desactiver_dortoir",
        "mettre_hors_service": "mettre_dortoir_hors_service",
        "reactiver": "modifier_dortoir",
        "generer_lits": "creer_lit",
    }


class PermissionLit(PermissionOrganisationBase):
    cible = "lit"
    action_permission_map = {
        "list": "consulter_hebergement",
        "retrieve": "consulter_hebergement",
        "create": "creer_lit",
        "update": "modifier_lit",
        "partial_update": "modifier_lit",
        "destroy": "mettre_lit_hors_service",
        "mettre_hors_service": "mettre_lit_hors_service",
        "reactiver": "reactiver_lit",
    }


class PermissionAttributionLit(PermissionOrganisationBase):
    cible = "attribution_lit"
    action_permission_map = {
        "list": "consulter_hebergement",
        "retrieve": "consulter_hebergement",
        "create": "attribuer_lit",
        "attribuer_manuellement": "attribuer_lit",
        "proposer_lot": "proposer_attribution_lit",
        "valider_lot": "attribuer_lit",
        "rejeter_lot": "modifier_attribution_lit",
        "destroy": "liberer_lit",
        "liberer": "liberer_lit",
        "progression": "consulter_hebergement",
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
    if isinstance(obj, RegleOrganisationCentre):
        return obj.session_id, obj.centre_id
    if isinstance(obj, Section):
        return obj.session_id, obj.centre_id
    if isinstance(obj, Groupe):
        return obj.section.session_id, obj.section.centre_id
    if isinstance(obj, AffectationGroupe):
        return (
            obj.affectation_centre.session_id,
            obj.affectation_centre.centre_id,
        )
    if isinstance(obj, Dortoir):
        return None, obj.centre_id
    if isinstance(obj, Lit):
        return None, obj.dortoir.centre_id
    if isinstance(obj, AttributionLit):
        return (
            obj.affectation_centre.session_id,
            obj.affectation_centre.centre_id,
        )
    return None, None


def contexte_pk(cible, pk):
    pk = _entier_ou_none(pk)
    if pk is None:
        return None, None

    modeles = {
        "regle": RegleOrganisationCentre,
        "section": Section,
        "groupe": Groupe,
        "affectation_groupe": AffectationGroupe,
        "dortoir": Dortoir,
        "lit": Lit,
        "attribution_lit": AttributionLit,
    }
    modele = modeles.get(cible)
    if not modele:
        return None, None

    objet = modele.objects.filter(pk=pk, deleted_at__isnull=True).first()
    return contexte_objet(objet) if objet else (None, None)


def contexte_relation(data):
    affectation_centre_id = _entier_ou_none(
        _premiere(data, "affectation_centre_id")
    )
    if affectation_centre_id:
        from affectations.models import AffectationCentre

        affectation = AffectationCentre.objects.filter(
            id=affectation_centre_id,
            deleted_at__isnull=True,
        ).first()
        if affectation:
            return affectation.session_id, affectation.centre_id

    section_id = _entier_ou_none(_premiere(data, "section_id"))
    if section_id:
        section = Section.objects.filter(
            id=section_id,
            deleted_at__isnull=True,
        ).first()
        if section:
            return section.session_id, section.centre_id

    groupe_id = _entier_ou_none(_premiere(data, "groupe_id"))
    if groupe_id:
        groupe = Groupe.objects.select_related("section").filter(
            id=groupe_id,
            deleted_at__isnull=True,
        ).first()
        if groupe:
            return groupe.section.session_id, groupe.section.centre_id

    dortoir_id = _entier_ou_none(_premiere(data, "dortoir_id"))
    if dortoir_id:
        dortoir = Dortoir.objects.filter(
            id=dortoir_id,
            deleted_at__isnull=True,
        ).first()
        if dortoir:
            return None, dortoir.centre_id

    lit_id = _entier_ou_none(_premiere(data, "lit_id"))
    if lit_id:
        lit = Lit.objects.select_related("dortoir").filter(
            id=lit_id,
            deleted_at__isnull=True,
        ).first()
        if lit:
            return None, lit.dortoir.centre_id

    return None, None


def contexte_affectation_courante(request=None):
    affectation_id = _entier_ou_none(obtenir_affectation_courante_id())
    if affectation_id is None:
        return None, None

    queryset = AffectationActeur.objects.filter(
        id=affectation_id,
        statut=AffectationActeur.Statut.ACTIVE,
        deleted_at__isnull=True,
    )
    acteur = getattr(request, "user", None)
    if acteur is not None and getattr(acteur, "is_authenticated", False):
        queryset = queryset.filter(acteur_id=acteur.id)

    affectation = queryset.only(
        "id",
        "acteur_id",
        "session_id",
        "niveau_affectation",
        "centre_id",
    ).first()
    if affectation is None:
        return None, None

    centre_id = (
        affectation.centre_id
        if affectation.niveau_affectation == AffectationActeur.NiveauAffectation.CENTRE
        else None
    )
    return affectation.session_id, centre_id


def extraire_perimetre_organisation(
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
    region_id = _entier_ou_none(
        _premiere(kwargs, "region_id")
        or _premiere(query, "region_id")
        or _premiere(data, "region_id")
    )

    if obj is not None:
        session_objet, centre_objet = contexte_objet(obj)
        session_id = session_objet or session_id
        centre_id = centre_objet or centre_id
    elif kwargs.get("pk"):
        session_objet, centre_objet = contexte_pk(cible, kwargs["pk"])
        session_id = session_objet or session_id
        centre_id = centre_objet or centre_id
    else:
        ids_lot = data.get("ids") or []
        if ids_lot:
            session_lot, centre_lot = contexte_pk(cible, ids_lot[0])
            session_id = session_lot or session_id
            centre_id = centre_lot or centre_id

        session_relation, centre_relation = contexte_relation(data)
        session_id = session_relation or session_id
        centre_id = centre_relation or centre_id

    region_code = None
    if centre_id:
        from affectations.models import CentreImmersion

        centre = CentreImmersion.objects.select_related("region").filter(
            id=centre_id,
            deleted_at__isnull=True,
        ).first()
        if centre:
            region_code = centre.region.code
    elif region_id:
        from affectations.models import RegionImmersion

        region = RegionImmersion.objects.filter(
            id=region_id,
            deleted_at__isnull=True,
        ).only("code").first()
        if region:
            region_code = region.code

    session_courante, centre_courant = contexte_affectation_courante(request)
    if session_id is None:
        session_id = session_courante
    if centre_id is None and region_code is None:
        centre_id = centre_courant
        if centre_id:
            from affectations.models import CentreImmersion

            centre = CentreImmersion.objects.select_related("region").filter(
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
