from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from django.db.models import Count, Exists, Max, OuterRef, Q
from django.utils import timezone

from affectations.models import AffectationCentre

from .models import RestrictionMedicale, VisiteMedicale


def _liste_ids(valeurs: Iterable[int] | None) -> list[int]:
    if not valeurs:
        return []
    return list(
        dict.fromkeys(
            int(valeur)
            for valeur in valeurs
            if valeur is not None
        )
    )


class VisiteMedicaleRepository:
    """Requêtes et persistance technique des visites médicales.

    Le repository ne décide jamais du résultat médical ni de ses conséquences.
    Ces règles appartiennent aux services.
    """

    @staticmethod
    def base_queryset():
        return VisiteMedicale.objects.select_related(
            "affectation_centre",
            "affectation_centre__immerge",
            "session",
            "centre",
            "agent_sante",
        ).prefetch_related("restrictions")

    @staticmethod
    def non_supprimees():
        return VisiteMedicaleRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def courantes():
        return VisiteMedicaleRepository.non_supprimees().filter(
            est_courante=True,
        )

    @staticmethod
    def validees():
        return VisiteMedicaleRepository.courantes().filter(
            statut=VisiteMedicale.Statut.VALIDEE,
        )

    @staticmethod
    def a_appliquer():
        return VisiteMedicaleRepository.validees().filter(
            statut_application__in=[
                VisiteMedicale.StatutApplication.A_APPLIQUER,
                VisiteMedicale.StatutApplication.ECHEC,
            ],
        )

    @staticmethod
    def filtrer(
        *,
        session_id=None,
        centre_id=None,
        affectation_centre_id=None,
        immerge_id=None,
        resultat=None,
        statut=None,
        statut_application=None,
        est_courante=None,
        recherche=None,
    ):
        queryset = VisiteMedicaleRepository.non_supprimees()

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if centre_id is not None:
            queryset = queryset.filter(centre_id=centre_id)
        if affectation_centre_id is not None:
            queryset = queryset.filter(
                affectation_centre_id=affectation_centre_id,
            )
        if immerge_id is not None:
            queryset = queryset.filter(
                affectation_centre__immerge_id=immerge_id,
            )
        if resultat:
            queryset = queryset.filter(resultat=resultat)
        if statut:
            queryset = queryset.filter(statut=statut)
        if statut_application:
            queryset = queryset.filter(
                statut_application=statut_application,
            )
        if est_courante is not None:
            queryset = queryset.filter(est_courante=bool(est_courante))
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(
                    affectation_centre__immerge__code_fasoim__icontains=(
                        recherche
                    )
                )
                | Q(centre__code__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
            )

        return queryset.order_by("-date_visite", "-id")

    @staticmethod
    def get_by_id(visite_id):
        return VisiteMedicaleRepository.non_supprimees().get(
            id=visite_id,
        )

    @staticmethod
    def get_by_id_ou_none(visite_id):
        return VisiteMedicaleRepository.non_supprimees().filter(
            id=visite_id,
        ).first()

    @staticmethod
    def get_by_id_pour_update(visite_id):
        return (
            VisiteMedicale.objects.select_for_update(of=("self",))
            .select_related(
                "affectation_centre",
                "affectation_centre__immerge",
                "affectation_centre__session__parametres",
                "session",
                "centre",
                "agent_sante",
            )
            .get(
                id=visite_id,
                deleted_at__isnull=True,
            )
        )

    @staticmethod
    def get_courante_par_affectation(affectation_centre_id):
        return (
            VisiteMedicaleRepository.courantes()
            .filter(
                affectation_centre_id=affectation_centre_id,
            )
            .first()
        )

    @staticmethod
    def get_courante_par_affectation_pour_update(
        affectation_centre_id,
    ):
        return (
            VisiteMedicale.objects.select_for_update(of=("self",))
            .select_related(
                "affectation_centre",
                "affectation_centre__immerge",
                "affectation_centre__session__parametres",
                "session",
                "centre",
                "agent_sante",
            )
            .filter(
                affectation_centre_id=affectation_centre_id,
                est_courante=True,
                deleted_at__isnull=True,
            )
            .first()
        )

    @staticmethod
    def dernier_numero_visite(affectation_centre_id):
        resultat = (
            VisiteMedicale.objects.filter(
                affectation_centre_id=affectation_centre_id,
            )
            .aggregate(maximum=Max("numero_visite"))
        )
        return int(resultat["maximum"] or 0)

    @staticmethod
    def verrouiller_par_ids(visite_ids):
        ids = _liste_ids(visite_ids)
        return (
            VisiteMedicale.objects.select_for_update(of=("self",))
            .select_related(
                "affectation_centre",
                "affectation_centre__immerge",
                "session",
                "centre",
                "agent_sante",
            )
            .filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .order_by("id")
        )

    @staticmethod
    def statistiques(*, session_id=None, centre_id=None):
        queryset = VisiteMedicaleRepository.validees().order_by()

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if centre_id is not None:
            queryset = queryset.filter(centre_id=centre_id)

        return queryset.values("resultat").annotate(
            total=Count("id"),
        ).order_by("resultat")

    @staticmethod
    def creer(**donnees):
        visite = VisiteMedicale(**donnees)
        visite.save()
        return visite

    @staticmethod
    def sauvegarder(visite, *, update_fields=None):
        visite.save(update_fields=update_fields)
        return visite


class RestrictionMedicaleRepository:
    """Requêtes relatives aux restrictions et consignes opérationnelles."""

    @staticmethod
    def base_queryset():
        return RestrictionMedicale.objects.select_related(
            "visite_medicale",
            "visite_medicale__affectation_centre",
            "visite_medicale__affectation_centre__immerge",
            "visite_medicale__session",
            "visite_medicale__centre",
            "saisie_par",
        )

    @staticmethod
    def non_supprimees():
        return RestrictionMedicaleRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def actives():
        return RestrictionMedicaleRepository.non_supprimees().filter(
            statut=RestrictionMedicale.Statut.ACTIVE,
        )

    @staticmethod
    def applicables(date_reference: date | None = None):
        jour = date_reference or timezone.localdate()
        return RestrictionMedicaleRepository.actives().filter(
            date_debut__lte=jour,
        ).filter(
            Q(date_fin__isnull=True)
            | Q(date_fin__gte=jour)
        ).filter(
            visite_medicale__deleted_at__isnull=True,
            visite_medicale__est_courante=True,
            visite_medicale__statut=VisiteMedicale.Statut.VALIDEE,
        )

    @staticmethod
    def filtrer(
        *,
        visite_medicale_id=None,
        session_id=None,
        centre_id=None,
        affectation_centre_id=None,
        module=None,
        type_restriction=None,
        statut=None,
        date_reference=None,
        seulement_applicables=False,
        recherche=None,
    ):
        queryset = (
            RestrictionMedicaleRepository.applicables(date_reference)
            if seulement_applicables
            else RestrictionMedicaleRepository.non_supprimees()
        )

        if visite_medicale_id is not None:
            queryset = queryset.filter(
                visite_medicale_id=visite_medicale_id,
            )
        if session_id is not None:
            queryset = queryset.filter(
                visite_medicale__session_id=session_id,
            )
        if centre_id is not None:
            queryset = queryset.filter(
                visite_medicale__centre_id=centre_id,
            )
        if affectation_centre_id is not None:
            queryset = queryset.filter(
                visite_medicale__affectation_centre_id=(
                    affectation_centre_id
                ),
            )
        if module:
            queryset = queryset.filter(
                modules_concernes__contains=[str(module)],
            )
        if type_restriction:
            queryset = queryset.filter(
                type_restriction=type_restriction,
            )
        if statut:
            queryset = queryset.filter(statut=statut)
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(libelle__icontains=recherche)
                | Q(consigne_operationnelle__icontains=recherche)
                | Q(
                    visite_medicale__affectation_centre__immerge__code_fasoim__icontains=(
                        recherche
                    )
                )
            )

        return queryset.order_by("-date_debut", "-id")

    @staticmethod
    def lister_par_visite(visite_medicale_id):
        return RestrictionMedicaleRepository.non_supprimees().filter(
            visite_medicale_id=visite_medicale_id,
        ).order_by("date_debut", "id")

    @staticmethod
    def lister_actives_par_visite(visite_medicale_id):
        return RestrictionMedicaleRepository.actives().filter(
            visite_medicale_id=visite_medicale_id,
        ).order_by("date_debut", "id")

    @staticmethod
    def applicables_pour_affectation_module(
        *,
        affectation_centre_id,
        module,
        date_reference=None,
    ):
        return RestrictionMedicaleRepository.applicables(
            date_reference,
        ).filter(
            visite_medicale__affectation_centre_id=(
                affectation_centre_id
            ),
            modules_concernes__contains=[str(module)],
        ).order_by("date_debut", "id")

    @staticmethod
    def get_by_id(restriction_id):
        return RestrictionMedicaleRepository.non_supprimees().get(
            id=restriction_id,
        )

    @staticmethod
    def get_by_id_pour_update(restriction_id):
        return (
            RestrictionMedicale.objects.select_for_update(of=("self",))
            .select_related(
                "visite_medicale",
                "visite_medicale__affectation_centre",
                "visite_medicale__affectation_centre__immerge",
                "saisie_par",
            )
            .get(
                id=restriction_id,
                deleted_at__isnull=True,
            )
        )

    @staticmethod
    def verrouiller_par_ids(restriction_ids):
        ids = _liste_ids(restriction_ids)
        return (
            RestrictionMedicale.objects.select_for_update(
                of=("self",)
            )
            .select_related(
                "visite_medicale",
                "visite_medicale__affectation_centre",
                "saisie_par",
            )
            .filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .order_by("id")
        )

    @staticmethod
    def creer(**donnees):
        restriction = RestrictionMedicale(**donnees)
        restriction.save()
        return restriction

    @staticmethod
    def sauvegarder(restriction, *, update_fields=None):
        restriction.save(update_fields=update_fields)
        return restriction


class CandidatVisiteMedicaleRepository:
    """Affectations centres éligibles à l'écran continu de visite."""

    @staticmethod
    def base_queryset():
        visite_courante = VisiteMedicale.objects.filter(
            affectation_centre_id=OuterRef("pk"),
            est_courante=True,
            deleted_at__isnull=True,
        )

        return (
            AffectationCentre.objects.select_related(
                "immerge",
                "session",
                "session__parametres",
                "centre",
                "centre__region",
            )
            .filter(
                statut=AffectationCentre.Statut.ACTIVE,
                deleted_at__isnull=True,
                session__deleted_at__isnull=True,
                centre__deleted_at__isnull=True,
            )
            .annotate(
                possede_visite_courante=Exists(visite_courante),
            )
        )

    @staticmethod
    def filtrer(
        *,
        session_id,
        centre_id,
        avec_visite_courante=None,
        recherche=None,
    ):
        queryset = CandidatVisiteMedicaleRepository.base_queryset().filter(
            session_id=session_id,
            centre_id=centre_id,
            session__parametres__visite_medicale_active=True,
        )

        if avec_visite_courante is not None:
            queryset = queryset.filter(
                possede_visite_courante=bool(
                    avec_visite_courante
                )
            )

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(immerge__code_fasoim__icontains=recherche)
                | Q(centre__code__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
            )

        return queryset.order_by(
            "possede_visite_courante",
            "immerge__code_fasoim",
            "id",
        )

    @staticmethod
    def sans_visite_courante(*, session_id, centre_id):
        return CandidatVisiteMedicaleRepository.filtrer(
            session_id=session_id,
            centre_id=centre_id,
            avec_visite_courante=False,
        )

    @staticmethod
    def prochaine_affectation(
        *,
        session_id,
        centre_id,
        apres_affectation_id=None,
    ):
        queryset = (
            CandidatVisiteMedicaleRepository.sans_visite_courante(
                session_id=session_id,
                centre_id=centre_id,
            )
        )

        if apres_affectation_id is not None:
            suivant = queryset.filter(
                id__gt=int(apres_affectation_id),
            ).first()
            if suivant:
                return suivant

        return queryset.first()

    @staticmethod
    def get_affectation_active(affectation_centre_id):
        return CandidatVisiteMedicaleRepository.base_queryset().get(
            id=affectation_centre_id,
        )

    @staticmethod
    def get_affectation_active_pour_update(
        affectation_centre_id,
    ):
        return (
            AffectationCentre.objects.select_for_update(of=("self",))
            .select_related(
                "immerge",
                "session",
                "session__parametres",
                "centre",
                "centre__region",
            )
            .get(
                id=affectation_centre_id,
                statut=AffectationCentre.Statut.ACTIVE,
                deleted_at__isnull=True,
                session__deleted_at__isnull=True,
                centre__deleted_at__isnull=True,
                session__parametres__visite_medicale_active=True,
            )
        )

    @staticmethod
    def compter_a_visiter(*, session_id, centre_id):
        return (
            CandidatVisiteMedicaleRepository.sans_visite_courante(
                session_id=session_id,
                centre_id=centre_id,
            )
            .count()
        )
