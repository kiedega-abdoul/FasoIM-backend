from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.models import Acteur, AffectationActeur
from accounts.repository import ControleAccesRepository
from accounts.service import ControleAccesService


class EstActeurDocumentsActif(BasePermission):
    message = "Acteur non authentifié ou inactif."

    def has_permission(self, request, view):
        acteur = getattr(request, "user", None)
        return bool(
            acteur
            and acteur.is_authenticated
            and isinstance(acteur, Acteur)
            and acteur.est_actif_metier
        )


class PermissionDocuments(BasePermission):
    """Contrôle les actions internes du module documents."""

    message = "Permission documents absente ou hors périmètre."

    ACTIONS = {
        # Résultats finaux
        "list": "consulter_resultats_finaux",
        "retrieve": "consulter_resultats_finaux",
        "statistiques": "consulter_resultats_finaux",
        "calculer_centre": "calculer_resultats_finaux",
        "valider_centre": "valider_resultats_centre",
        # Publications
        "soumettre_arrivee": "soumettre_publication_centre",
        "soumettre_attestations": "soumettre_publication_centre",
        "valider_region": "valider_publication_region",
        "signer_attestations": "signer_attestations_region",
        "rejeter_region": "rejeter_publication_region",
        "publier_session": "publier_documents_session",
        # Fichiers
        "generer_attestations": "generer_attestations",
        "generer_rapport": "generer_rapports",
        "telecharger": "telecharger_document",
        "progression": "consulter_documents",
        # Clôture
        "verifier_cloture": "verifier_cloture_session",
    }

    def _code(self, view):
        action = getattr(view, "action", None) or getattr(view, "action_code", None)
        mapping = getattr(view, "permission_code_map", self.ACTIONS)
        if action == "publier_session":
            type_publication = str(
                getattr(getattr(view, "request", None), "data", {}).get("type_publication", "")
            )
            return (
                "publier_attestations"
                if type_publication == "ATTESTATIONS"
                else "publier_informations_arrivee"
            )
        return mapping.get(action)

    @staticmethod
    def _perimetre(request):
        data = getattr(request, "data", {}) or {}
        query = getattr(request, "query_params", {}) or {}
        session_id = query.get("session") or query.get("session_id") or data.get("session") or data.get("session_id")
        centre_id = query.get("centre") or query.get("centre_id") or data.get("centre") or data.get("centre_id")
        region_code = query.get("region_code") or data.get("region_code")
        return session_id, region_code, centre_id

    def has_permission(self, request, view):
        acteur = getattr(request, "user", None)
        if not acteur or not getattr(acteur, "est_actif_metier", False):
            return False
        if acteur.is_superuser:
            return True

        code = self._code(view)
        if not code:
            self.message = "Action documents non autorisée."
            return False

        session_id, region_code, centre_id = self._perimetre(request)
        if session_id or region_code or centre_id:
            resultat = ControleAccesService.acteur_peut(
                acteur,
                code,
                session_id=session_id,
                region_code=region_code,
                centre_id=centre_id,
            )
            if not resultat.autorise:
                self.message = resultat.motif or self.message
            return resultat.autorise

        affectations = AffectationActeur.objects.filter(
            acteur_id=acteur.id,
            statut=AffectationActeur.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).select_related("session")
        for affectation in affectations:
            if ControleAccesRepository.acteur_a_permission(acteur, affectation, code):
                return True
        return False

    def has_object_permission(self, request, view, obj):
        acteur = request.user
        if acteur.is_superuser:
            return True
        code = self._code(view) or "consulter_documents"
        region_code = None
        if getattr(obj, "region_id", None):
            region_code = obj.region.code
        elif getattr(obj, "centre_id", None):
            region_code = obj.centre.region.code
        resultat = ControleAccesService.acteur_peut(
            acteur,
            code,
            session_id=getattr(obj, "session_id", None),
            region_code=region_code,
            centre_id=getattr(obj, "centre_id", None),
        )
        if not resultat.autorise:
            self.message = resultat.motif or self.message
        return resultat.autorise
