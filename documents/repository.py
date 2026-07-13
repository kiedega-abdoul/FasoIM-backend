from __future__ import annotations

from django.db.models import Count, Q

from accounts.models import AffectationActeur
from accounts.repository import ControleAccesRepository

from .models import DocumentGenere, PublicationOfficielle, ResultatFinal


class PerimetreDocumentsRepository:
    """Applique le périmètre des affectations de l'acteur aux documents."""

    @staticmethod
    def filtrer(queryset, acteur, code_permission):
        if not acteur or not getattr(acteur, "is_authenticated", False):
            return queryset.none()
        if getattr(acteur, "is_superuser", False):
            return queryset

        affectations = AffectationActeur.objects.filter(
            acteur_id=acteur.id,
            statut=AffectationActeur.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).select_related("session")

        filtre_total = Q()
        trouve = False
        for affectation in affectations:
            # Le traitement documentaire s'effectue avant TERMINEE. On accepte
            # aussi une affectation dont les dates restent valides même si le
            # service appelle ce filtre pendant la transition de clôture.
            if affectation.deleted_at is not None or affectation.statut != AffectationActeur.Statut.ACTIVE:
                continue
            if not ControleAccesRepository.acteur_a_permission(
                acteur,
                affectation,
                code_permission,
            ):
                continue
            trouve = True
            filtre = Q()
            if affectation.session_id:
                filtre &= Q(session_id=affectation.session_id)
            if affectation.niveau_affectation in {
                AffectationActeur.NiveauAffectation.PLATEFORME,
                AffectationActeur.NiveauAffectation.NATIONAL,
            }:
                filtre_total |= filtre
            elif affectation.niveau_affectation == AffectationActeur.NiveauAffectation.REGION:
                filtre_total |= filtre & (
                    Q(region__code__iexact=affectation.region_code)
                    | Q(centre__region__code__iexact=affectation.region_code)
                )
            elif affectation.niveau_affectation == AffectationActeur.NiveauAffectation.CENTRE:
                filtre_total |= filtre & Q(centre_id=affectation.centre_id)
        if not trouve:
            return queryset.none()
        return queryset.filter(filtre_total).distinct()


class ResultatFinalRepository:
    @staticmethod
    def base_queryset():
        return ResultatFinal.objects.select_related(
            "session",
            "region",
            "centre",
            "affectation_centre",
            "affectation_centre__immerge",
            "immerge",
            "calcule_par",
            "valide_centre_par",
            "valide_region_par",
        )

    @classmethod
    def actifs(cls):
        return cls.base_queryset().filter(deleted_at__isnull=True)

    @classmethod
    def visibles_par_acteur(cls, acteur, code_permission="consulter_resultats_finaux"):
        return PerimetreDocumentsRepository.filtrer(cls.actifs(), acteur, code_permission)

    @classmethod
    def filtrer(cls, queryset, params):
        params = params or {}
        mapping = {
            "session": "session_id",
            "region": "region_id",
            "centre": "centre_id",
            "immerge": "immerge_id",
            "affectation_centre": "affectation_centre_id",
        }
        for parametre, champ in mapping.items():
            valeur = params.get(parametre)
            if valeur not in (None, ""):
                try:
                    queryset = queryset.filter(**{champ: int(valeur)})
                except (TypeError, ValueError):
                    return queryset.none()
        if params.get("decision"):
            queryset = queryset.filter(decision=params["decision"])
        if params.get("statut"):
            queryset = queryset.filter(statut=params["statut"])
        recherche = str(params.get("recherche") or "").strip()
        if recherche:
            queryset = queryset.filter(
                Q(immerge__code_fasoim__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
                | Q(region__nom__icontains=recherche)
            )
        return queryset.order_by("centre__nom", "immerge__code_fasoim")

    @classmethod
    def get_by_id(cls, resultat_id):
        return cls.actifs().get(id=resultat_id)

    @classmethod
    def get_by_id_pour_update(cls, resultat_id):
        return (
            ResultatFinal.objects.select_for_update(of=("self",))
            .select_related(
                "session", "region", "centre", "affectation_centre", "immerge"
            )
            .get(id=resultat_id, deleted_at__isnull=True)
        )

    @classmethod
    def get_par_affectation(cls, affectation_centre_id):
        return cls.actifs().filter(affectation_centre_id=affectation_centre_id).first()

    @classmethod
    def lister_centre(cls, session_id, centre_id):
        return cls.actifs().filter(session_id=session_id, centre_id=centre_id)

    @classmethod
    def lister_region(cls, session_id, region_id):
        return cls.actifs().filter(session_id=session_id, region_id=region_id)

    @classmethod
    def statistiques(cls, queryset):
        return queryset.aggregate(
            total=Count("id"),
            eligibles=Count("id", filter=Q(decision=ResultatFinal.Decision.ELIGIBLE)),
            non_eligibles=Count("id", filter=Q(decision=ResultatFinal.Decision.NON_ELIGIBLE)),
            a_verifier=Count("id", filter=Q(decision=ResultatFinal.Decision.A_VERIFIER)),
            publies=Count("id", filter=Q(statut=ResultatFinal.Statut.PUBLIE)),
        )


class PublicationOfficielleRepository:
    @staticmethod
    def base_queryset():
        return PublicationOfficielle.objects.select_related(
            "session",
            "region",
            "centre",
            "preparee_par",
            "soumise_par",
            "validee_region_par",
            "publiee_par",
            "remplace_publication",
        )

    @classmethod
    def actives(cls):
        return cls.base_queryset().filter(deleted_at__isnull=True)

    @classmethod
    def visibles_par_acteur(cls, acteur, code_permission="consulter_publications"):
        return PerimetreDocumentsRepository.filtrer(cls.actives(), acteur, code_permission)

    @classmethod
    def filtrer(cls, queryset, params):
        params = params or {}
        for parametre, champ in {
            "session": "session_id",
            "region": "region_id",
            "centre": "centre_id",
        }.items():
            valeur = params.get(parametre)
            if valeur not in (None, ""):
                try:
                    queryset = queryset.filter(**{champ: int(valeur)})
                except (TypeError, ValueError):
                    return queryset.none()
        if params.get("type_publication"):
            queryset = queryset.filter(type_publication=params["type_publication"])
        if params.get("statut"):
            queryset = queryset.filter(statut=params["statut"])
        if params.get("perimetre"):
            queryset = queryset.filter(perimetre=params["perimetre"])
        return queryset.order_by("-created_at")

    @classmethod
    def get_by_id(cls, publication_id):
        return cls.actives().get(id=publication_id)

    @classmethod
    def get_by_id_pour_update(cls, publication_id):
        return (
            PublicationOfficielle.objects.select_for_update(of=("self",))
            .select_related("session", "region", "centre")
            .get(id=publication_id, deleted_at__isnull=True)
        )

    @classmethod
    def get_centre_courante(cls, *, session_id, centre_id, type_publication):
        return (
            cls.actives()
            .filter(
                session_id=session_id,
                centre_id=centre_id,
                type_publication=type_publication,
            )
            .exclude(statut__in=[
                PublicationOfficielle.Statut.REMPLACEE,
                PublicationOfficielle.Statut.ANNULEE,
            ])
            .order_by("-version", "-id")
            .first()
        )

    @classmethod
    def publication_active_centre(cls, *, session_id, centre_id, type_publication):
        return cls.actives().filter(
            session_id=session_id,
            centre_id=centre_id,
            type_publication=type_publication,
            statut=PublicationOfficielle.Statut.PUBLIEE,
        ).order_by("-version", "-id").first()

    @classmethod
    def centres_session(cls, *, session_id, type_publication):
        return cls.actives().filter(
            session_id=session_id,
            type_publication=type_publication,
            perimetre=PublicationOfficielle.Perimetre.CENTRE,
        )


class DocumentGenereRepository:
    @staticmethod
    def base_queryset():
        return DocumentGenere.objects.select_related(
            "session",
            "region",
            "centre",
            "immerge",
            "affectation_centre",
            "resultat_final",
            "publication",
            "genere_par",
            "signataire",
            "remplace_document",
        )

    @classmethod
    def actifs(cls):
        return cls.base_queryset().filter(deleted_at__isnull=True)

    @classmethod
    def visibles_par_acteur(cls, acteur, code_permission="consulter_documents"):
        return PerimetreDocumentsRepository.filtrer(cls.actifs(), acteur, code_permission)

    @classmethod
    def filtrer(cls, queryset, params):
        params = params or {}
        for parametre, champ in {
            "session": "session_id",
            "region": "region_id",
            "centre": "centre_id",
            "immerge": "immerge_id",
            "publication": "publication_id",
        }.items():
            valeur = params.get(parametre)
            if valeur not in (None, ""):
                try:
                    queryset = queryset.filter(**{champ: int(valeur)})
                except (TypeError, ValueError):
                    return queryset.none()
        if params.get("type_document"):
            queryset = queryset.filter(type_document=params["type_document"])
        if params.get("format_fichier"):
            queryset = queryset.filter(format_fichier=params["format_fichier"])
        if params.get("statut"):
            queryset = queryset.filter(statut=params["statut"])
        recherche = str(params.get("recherche") or "").strip()
        if recherche:
            queryset = queryset.filter(
                Q(numero_document__icontains=recherche)
                | Q(titre__icontains=recherche)
                | Q(immerge__code_fasoim__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
            )
        return queryset.order_by("-created_at")

    @classmethod
    def get_by_id(cls, document_id):
        return cls.actifs().get(id=document_id)

    @classmethod
    def get_by_id_pour_update(cls, document_id):
        return (
            DocumentGenere.objects.select_for_update(of=("self",))
            .select_related(
                "session", "region", "centre", "immerge", "resultat_final", "publication"
            )
            .get(id=document_id, deleted_at__isnull=True)
        )

    @classmethod
    def get_par_code_verification(cls, code):
        return cls.actifs().filter(code_verification__iexact=str(code).strip()).first()

    @classmethod
    def get_par_numero(cls, numero):
        return cls.actifs().filter(numero_document__iexact=str(numero).strip()).first()

    @classmethod
    def get_attestation_resultat(cls, resultat_id):
        return cls.actifs().filter(
            resultat_final_id=resultat_id,
            type_document=DocumentGenere.TypeDocument.ATTESTATION,
        ).exclude(statut__in=[
            DocumentGenere.Statut.ANNULE,
            DocumentGenere.Statut.REMPLACE,
            DocumentGenere.Statut.ECHEC,
        ]).first()
