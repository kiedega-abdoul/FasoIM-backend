from __future__ import annotations

from collections.abc import Iterable

from django.db.models import Count, Exists, OuterRef, Q, Sum, Value
from django.db.models.functions import Coalesce

from affectations.models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)

from .models import (
    STATUTS_AFFECTATION_GROUPE_OUVERTS,
    STATUTS_ATTRIBUTION_LIT_OUVERTS,
    AffectationGroupe,
    AttributionLit,
    Dortoir,
    Groupe,
    Lit,
    RegleOrganisationCentre,
    Section,
)


STATUTS_GROUPES_OUVERTS = tuple(STATUTS_AFFECTATION_GROUPE_OUVERTS)
STATUTS_LITS_OUVERTS = tuple(STATUTS_ATTRIBUTION_LIT_OUVERTS)


def _liste_ids(valeurs: Iterable[int] | None) -> list[int]:
    """Nettoie une liste d'identifiants sans appliquer de règle métier."""

    if not valeurs:
        return []
    return list(dict.fromkeys(
        int(valeur)
        for valeur in valeurs
        if valeur is not None
    ))


def _liste_statuts(
    valeurs: Iterable[str] | None,
    statuts_defaut: Iterable[str],
) -> list[str]:
    """Nettoie une liste de statuts avec plusieurs valeurs par défaut."""

    source = statuts_defaut if valeurs is None else valeurs
    return list(dict.fromkeys(
        str(valeur)
        for valeur in source
        if valeur
    ))


def _limite_lot(limite: int | None) -> int | None:
    """Valide seulement la forme technique d'une taille de lot."""

    if limite is None:
        return None

    limite = int(limite)
    if limite <= 0:
        raise ValueError("La taille du lot doit être strictement positive.")
    return limite


class RegleOrganisationCentreRepository:
    """Requêtes relatives aux règles locales d'un centre."""

    @staticmethod
    def base_queryset():
        return RegleOrganisationCentre.objects.select_related(
            "session",
            "centre",
            "centre__region",
            "validee_par",
        )

    @staticmethod
    def actifs():
        return RegleOrganisationCentreRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def lister():
        return RegleOrganisationCentreRepository.actifs().order_by(
            "-session_id",
            "centre__nom",
            "id",
        )

    @staticmethod
    def filtrer(
        *,
        session_id=None,
        centre_id=None,
        region_id=None,
        statut=None,
        recherche=None,
    ):
        queryset = RegleOrganisationCentreRepository.actifs()

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if centre_id is not None:
            queryset = queryset.filter(centre_id=centre_id)
        if region_id is not None:
            queryset = queryset.filter(centre__region_id=region_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(session__code__icontains=recherche)
                | Q(session__nom__icontains=recherche)
                | Q(centre__code__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
                | Q(lieu_accueil__icontains=recherche)
            )

        return queryset.order_by("-session_id", "centre__nom", "id")

    @staticmethod
    def get_by_id(regle_id):
        return RegleOrganisationCentreRepository.actifs().get(id=regle_id)

    @staticmethod
    def get_par_session_centre(session_id, centre_id):
        return RegleOrganisationCentreRepository.actifs().get(
            session_id=session_id,
            centre_id=centre_id,
        )

    @staticmethod
    def get_par_session_centre_ou_none(session_id, centre_id):
        return RegleOrganisationCentreRepository.actifs().filter(
            session_id=session_id,
            centre_id=centre_id,
        ).first()

    @staticmethod
    def get_par_session_centre_pour_update(session_id, centre_id):
        return (
            RegleOrganisationCentre.objects.filter(
                session_id=session_id,
                centre_id=centre_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related("session", "centre", "centre__region")
            .get()
        )

    @staticmethod
    def verrouiller_par_ids(regle_ids):
        ids = _liste_ids(regle_ids)
        return (
            RegleOrganisationCentre.objects.filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def existe_pour_session_centre(
        session_id,
        centre_id,
        *,
        exclure_id=None,
    ):
        queryset = RegleOrganisationCentreRepository.actifs().filter(
            session_id=session_id,
            centre_id=centre_id,
        )
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def creer(**donnees):
        regle = RegleOrganisationCentre(**donnees)
        regle.full_clean()
        regle.save()
        return regle

    @staticmethod
    def sauvegarder(regle, *, update_fields=None):
        regle.full_clean()
        regle.save(update_fields=update_fields)
        return regle


class SectionRepository:
    """Requêtes sur les sections, sans calculer leur nombre optimal."""

    @staticmethod
    def base_queryset():
        return Section.objects.select_related(
            "session",
            "centre",
            "centre__region",
        )

    @staticmethod
    def actifs():
        return SectionRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def lister():
        return SectionRepository.actifs().order_by(
            "session_id",
            "centre__nom",
            "code",
            "id",
        )

    @staticmethod
    def lister_actives():
        return SectionRepository.actifs().filter(
            statut=Section.Statut.ACTIVE,
            centre__deleted_at__isnull=True,
            centre__statut=CentreImmersion.Statut.ACTIF,
            centre__region__deleted_at__isnull=True,
            centre__region__statut=RegionImmersion.Statut.ACTIVE,
        ).order_by("centre__nom", "code", "id")

    @staticmethod
    def filtrer(
        *,
        session_id=None,
        centre_id=None,
        region_id=None,
        statut=None,
        recherche=None,
    ):
        queryset = SectionRepository.actifs()

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if centre_id is not None:
            queryset = queryset.filter(centre_id=centre_id)
        if region_id is not None:
            queryset = queryset.filter(centre__region_id=region_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(code__icontains=recherche)
                | Q(nom__icontains=recherche)
                | Q(centre__code__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
            )

        return queryset.order_by("centre__nom", "code", "id")

    @staticmethod
    def lister_par_session_centre(session_id, centre_id):
        return SectionRepository.lister_actives().filter(
            session_id=session_id,
            centre_id=centre_id,
        )

    @staticmethod
    def lister_donnees_algorithme(session_id, centre_id):
        return SectionRepository.lister_par_session_centre(
            session_id,
            centre_id,
        ).values(
            "id",
            "session_id",
            "centre_id",
            "code",
            "nom",
            "capacite_max",
        )

    @staticmethod
    def get_by_id(section_id):
        return SectionRepository.actifs().get(id=section_id)

    @staticmethod
    def get_by_id_pour_update(section_id):
        return (
            Section.objects.filter(
                id=section_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related("session", "centre", "centre__region")
            .get()
        )

    @staticmethod
    def verrouiller_par_ids(section_ids):
        ids = _liste_ids(section_ids)
        return (
            Section.objects.filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def verrouiller_par_session_centre(session_id, centre_id):
        return (
            Section.objects.filter(
                session_id=session_id,
                centre_id=centre_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def existe_code(
        session_id,
        centre_id,
        code,
        *,
        exclure_id=None,
    ):
        queryset = SectionRepository.actifs().filter(
            session_id=session_id,
            centre_id=centre_id,
            code=code,
        )
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def compter_par_session_centre(session_id, centre_id):
        return SectionRepository.lister_par_session_centre(
            session_id,
            centre_id,
        ).count()

    @staticmethod
    def capacite_totale_par_session_centre(session_id, centre_id):
        resultat = SectionRepository.lister_par_session_centre(
            session_id,
            centre_id,
        ).aggregate(
            total=Coalesce(Sum("capacite_max"), Value(0)),
        )
        return int(resultat["total"] or 0)

    @staticmethod
    def creer(**donnees):
        section = Section(**donnees)
        section.full_clean()
        section.save()
        return section

    @staticmethod
    def creer_en_lot(objets, *, batch_size=500):
        objets = list(objets)
        if not objets:
            return []
        return Section.objects.bulk_create(
            objets,
            batch_size=batch_size,
        )

    @staticmethod
    def mettre_a_jour_en_lot(
        objets,
        champs,
        *,
        batch_size=500,
    ):
        objets = list(objets)
        if not objets:
            return 0
        Section.objects.bulk_update(
            objets,
            champs,
            batch_size=batch_size,
        )
        return len(objets)

    @staticmethod
    def sauvegarder(section, *, update_fields=None):
        section.full_clean()
        section.save(update_fields=update_fields)
        return section


class GroupeRepository:
    """Requêtes sur les groupes et leurs capacités déclarées."""

    @staticmethod
    def base_queryset():
        return Groupe.objects.select_related(
            "section",
            "section__session",
            "section__centre",
            "section__centre__region",
        )

    @staticmethod
    def actifs():
        return GroupeRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def lister():
        return GroupeRepository.actifs().order_by(
            "section__centre__nom",
            "section__code",
            "code",
            "id",
        )

    @staticmethod
    def lister_actifs():
        return GroupeRepository.actifs().filter(
            statut=Groupe.Statut.ACTIF,
            section__deleted_at__isnull=True,
            section__statut=Section.Statut.ACTIVE,
            section__centre__deleted_at__isnull=True,
            section__centre__statut=CentreImmersion.Statut.ACTIF,
        ).order_by("section__code", "code", "id")

    @staticmethod
    def filtrer(
        *,
        session_id=None,
        centre_id=None,
        section_id=None,
        region_id=None,
        statut=None,
        recherche=None,
    ):
        queryset = GroupeRepository.actifs()

        if session_id is not None:
            queryset = queryset.filter(section__session_id=session_id)
        if centre_id is not None:
            queryset = queryset.filter(section__centre_id=centre_id)
        if section_id is not None:
            queryset = queryset.filter(section_id=section_id)
        if region_id is not None:
            queryset = queryset.filter(
                section__centre__region_id=region_id,
            )
        if statut:
            queryset = queryset.filter(statut=statut)
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(code__icontains=recherche)
                | Q(nom__icontains=recherche)
                | Q(section__code__icontains=recherche)
                | Q(section__nom__icontains=recherche)
                | Q(section__centre__code__icontains=recherche)
                | Q(section__centre__nom__icontains=recherche)
            )

        return queryset.order_by(
            "section__code",
            "code",
            "id",
        )

    @staticmethod
    def lister_par_session_centre(session_id, centre_id):
        return GroupeRepository.lister_actifs().filter(
            section__session_id=session_id,
            section__centre_id=centre_id,
        )

    @staticmethod
    def lister_par_section(section_id):
        return GroupeRepository.lister_actifs().filter(
            section_id=section_id,
        )

    @staticmethod
    def lister_donnees_algorithme(session_id, centre_id):
        return GroupeRepository.lister_par_session_centre(
            session_id,
            centre_id,
        ).values(
            "id",
            "section_id",
            "section__code",
            "section__capacite_max",
            "code",
            "nom",
            "capacite_max",
        )

    @staticmethod
    def capacites_totales_par_section(
        *,
        session_id=None,
        centre_id=None,
        section_ids=None,
    ):
        queryset = GroupeRepository.lister_actifs().order_by()

        if session_id is not None:
            queryset = queryset.filter(section__session_id=session_id)
        if centre_id is not None:
            queryset = queryset.filter(section__centre_id=centre_id)
        if section_ids:
            queryset = queryset.filter(
                section_id__in=_liste_ids(section_ids),
            )

        return (
            queryset.values("section_id")
            .annotate(
                capacite_totale_groupes=Coalesce(
                    Sum("capacite_max"),
                    Value(0),
                ),
                nombre_groupes=Count("id"),
            )
            .order_by("section_id")
        )

    @staticmethod
    def get_by_id(groupe_id):
        return GroupeRepository.actifs().get(id=groupe_id)

    @staticmethod
    def get_by_id_pour_update(groupe_id):
        return (
            Groupe.objects.filter(
                id=groupe_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related(
                "section",
                "section__session",
                "section__centre",
            )
            .get()
        )

    @staticmethod
    def verrouiller_par_ids(groupe_ids):
        ids = _liste_ids(groupe_ids)
        return (
            Groupe.objects.filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def verrouiller_par_session_centre(session_id, centre_id):
        return (
            Groupe.objects.filter(
                section__session_id=session_id,
                section__centre_id=centre_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def existe_code(section_id, code, *, exclure_id=None):
        queryset = GroupeRepository.actifs().filter(
            section_id=section_id,
            code=code,
        )
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def creer(**donnees):
        groupe = Groupe(**donnees)
        groupe.full_clean()
        groupe.save()
        return groupe

    @staticmethod
    def creer_en_lot(objets, *, batch_size=1000):
        objets = list(objets)
        if not objets:
            return []
        return Groupe.objects.bulk_create(
            objets,
            batch_size=batch_size,
        )

    @staticmethod
    def mettre_a_jour_en_lot(
        objets,
        champs,
        *,
        batch_size=1000,
    ):
        objets = list(objets)
        if not objets:
            return 0
        Groupe.objects.bulk_update(
            objets,
            champs,
            batch_size=batch_size,
        )
        return len(objets)

    @staticmethod
    def sauvegarder(groupe, *, update_fields=None):
        groupe.full_clean()
        groupe.save(update_fields=update_fields)
        return groupe


class CandidatsOrganisationRepository:
    """Sélection technique des immergés à organiser.

    Le repository sélectionne et verrouille les AffectationCentre actives.
    Les décisions de répartition appartiennent exclusivement au service.
    """

    @staticmethod
    def base_affectations_centres():
        return AffectationCentre.objects.select_related(
            "immerge",
            "session",
            "centre",
            "centre__region",
            "affectation_regionale",
        ).filter(
            deleted_at__isnull=True,
            statut=AffectationCentre.Statut.ACTIVE,
            centre__deleted_at__isnull=True,
            centre__statut=CentreImmersion.Statut.ACTIF,
            centre__region__deleted_at__isnull=True,
            centre__region__statut=RegionImmersion.Statut.ACTIVE,
        )

    @staticmethod
    def filtrer_affectations_centres(
        *,
        session_id,
        centre_id,
        affectation_centre_ids=None,
    ):
        queryset = CandidatsOrganisationRepository.base_affectations_centres().filter(
            session_id=session_id,
            centre_id=centre_id,
        )
        if affectation_centre_ids:
            queryset = queryset.filter(
                id__in=_liste_ids(affectation_centre_ids),
            )
        return queryset.order_by("id")

    @staticmethod
    def candidats_groupes(
        *,
        session_id,
        centre_id,
        limite=None,
    ):
        affectation_ouverte = AffectationGroupe.objects.filter(
            affectation_centre_id=OuterRef("pk"),
            statut__in=STATUTS_GROUPES_OUVERTS,
            deleted_at__isnull=True,
        )
        queryset = (
            CandidatsOrganisationRepository.filtrer_affectations_centres(
                session_id=session_id,
                centre_id=centre_id,
            )
            .annotate(
                possede_affectation_groupe_ouverte=Exists(
                    affectation_ouverte
                )
            )
            .filter(possede_affectation_groupe_ouverte=False)
            .order_by("id")
        )

        limite = _limite_lot(limite)
        return queryset[:limite] if limite is not None else queryset

    @staticmethod
    def compter_candidats_groupes(*, session_id, centre_id):
        return CandidatsOrganisationRepository.candidats_groupes(
            session_id=session_id,
            centre_id=centre_id,
        ).count()

    @staticmethod
    def verrouiller_lot_candidats_groupes(
        *,
        session_id,
        centre_id,
        limite,
    ):
        limite = _limite_lot(limite)
        affectation_ouverte = AffectationGroupe.objects.filter(
            affectation_centre_id=OuterRef("pk"),
            statut__in=STATUTS_GROUPES_OUVERTS,
            deleted_at__isnull=True,
        )
        return (
            CandidatsOrganisationRepository.filtrer_affectations_centres(
                session_id=session_id,
                centre_id=centre_id,
            )
            .annotate(
                possede_affectation_groupe_ouverte=Exists(
                    affectation_ouverte
                )
            )
            .filter(possede_affectation_groupe_ouverte=False)
            .select_for_update(of=("self",), skip_locked=True)
            .order_by("id")[:limite]
        )

    @staticmethod
    def candidats_lits(
        *,
        session_id,
        centre_id,
        limite=None,
    ):
        attribution_ouverte = AttributionLit.objects.filter(
            affectation_centre_id=OuterRef("pk"),
            statut__in=STATUTS_LITS_OUVERTS,
            deleted_at__isnull=True,
        )
        queryset = (
            CandidatsOrganisationRepository.filtrer_affectations_centres(
                session_id=session_id,
                centre_id=centre_id,
            )
            .annotate(
                possede_attribution_lit_ouverte=Exists(
                    attribution_ouverte
                )
            )
            .filter(possede_attribution_lit_ouverte=False)
            .order_by("id")
        )

        limite = _limite_lot(limite)
        return queryset[:limite] if limite is not None else queryset

    @staticmethod
    def compter_candidats_lits(*, session_id, centre_id):
        return CandidatsOrganisationRepository.candidats_lits(
            session_id=session_id,
            centre_id=centre_id,
        ).count()

    @staticmethod
    def verrouiller_lot_candidats_lits(
        *,
        session_id,
        centre_id,
        limite,
    ):
        limite = _limite_lot(limite)
        attribution_ouverte = AttributionLit.objects.filter(
            affectation_centre_id=OuterRef("pk"),
            statut__in=STATUTS_LITS_OUVERTS,
            deleted_at__isnull=True,
        )
        return (
            CandidatsOrganisationRepository.filtrer_affectations_centres(
                session_id=session_id,
                centre_id=centre_id,
            )
            .annotate(
                possede_attribution_lit_ouverte=Exists(
                    attribution_ouverte
                )
            )
            .filter(possede_attribution_lit_ouverte=False)
            .select_for_update(of=("self",), skip_locked=True)
            .order_by("id")[:limite]
        )

    @staticmethod
    def compter_affectations_centre_actives(
        *,
        session_id,
        centre_id,
    ):
        return CandidatsOrganisationRepository.filtrer_affectations_centres(
            session_id=session_id,
            centre_id=centre_id,
        ).count()

    @staticmethod
    def verrouiller_affectations_centres_par_ids(
        affectation_centre_ids,
    ):
        ids = _liste_ids(affectation_centre_ids)
        return (
            AffectationCentre.objects.filter(
                id__in=ids,
                deleted_at__isnull=True,
                statut=AffectationCentre.Statut.ACTIVE,
            )
            .select_for_update(of=("self",))
            .select_related(
                "immerge",
                "session",
                "centre",
                "centre__region",
            )
            .order_by("id")
        )


class AffectationGroupeRepository:
    """Persistance et consultation des affectations aux groupes."""

    @staticmethod
    def base_queryset():
        return AffectationGroupe.objects.select_related(
            "affectation_centre",
            "affectation_centre__immerge",
            "affectation_centre__session",
            "affectation_centre__centre",
            "affectation_centre__centre__region",
            "groupe",
            "groupe__section",
            "affecte_par",
        )

    @staticmethod
    def non_supprimees():
        return AffectationGroupeRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def lister():
        return AffectationGroupeRepository.non_supprimees().order_by(
            "-date_affectation",
            "-id",
        )

    @staticmethod
    def lister_ouvertes():
        return AffectationGroupeRepository.non_supprimees().filter(
            statut__in=STATUTS_GROUPES_OUVERTS,
        ).order_by("-date_affectation", "-id")

    @staticmethod
    def lister_proposees():
        return AffectationGroupeRepository.non_supprimees().filter(
            statut=AffectationGroupe.Statut.PROPOSEE,
        ).order_by("-date_affectation", "-id")

    @staticmethod
    def lister_actives():
        return AffectationGroupeRepository.non_supprimees().filter(
            statut=AffectationGroupe.Statut.ACTIVE,
        ).order_by("-date_affectation", "-id")

    @staticmethod
    def lister_a_reorganiser():
        return AffectationGroupeRepository.non_supprimees().filter(
            statut=AffectationGroupe.Statut.A_REORGANISER,
        ).order_by("-date_affectation", "-id")

    @staticmethod
    def filtrer(
        *,
        session_id=None,
        centre_id=None,
        region_id=None,
        section_id=None,
        groupe_id=None,
        statut=None,
        affectation_centre_id=None,
        recherche=None,
    ):
        queryset = AffectationGroupeRepository.non_supprimees()

        if session_id is not None:
            queryset = queryset.filter(
                affectation_centre__session_id=session_id,
            )
        if centre_id is not None:
            queryset = queryset.filter(
                affectation_centre__centre_id=centre_id,
            )
        if region_id is not None:
            queryset = queryset.filter(
                affectation_centre__centre__region_id=region_id,
            )
        if section_id is not None:
            queryset = queryset.filter(groupe__section_id=section_id)
        if groupe_id is not None:
            queryset = queryset.filter(groupe_id=groupe_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if affectation_centre_id is not None:
            queryset = queryset.filter(
                affectation_centre_id=affectation_centre_id,
            )
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(
                    affectation_centre__immerge__code_fasoim__icontains=
                    recherche
                )
                | Q(groupe__code__icontains=recherche)
                | Q(groupe__nom__icontains=recherche)
                | Q(groupe__section__code__icontains=recherche)
                | Q(observations__icontains=recherche)
            )

        return queryset.order_by("-date_affectation", "-id")

    @staticmethod
    def get_by_id(affectation_id):
        return AffectationGroupeRepository.non_supprimees().get(
            id=affectation_id,
        )

    @staticmethod
    def get_ouverte_par_affectation_centre(
        affectation_centre_id,
    ):
        return AffectationGroupeRepository.lister_ouvertes().filter(
            affectation_centre_id=affectation_centre_id,
        ).first()

    @staticmethod
    def get_ouverte_par_affectation_centre_pour_update(
        affectation_centre_id,
    ):
        return (
            AffectationGroupe.objects.filter(
                affectation_centre_id=affectation_centre_id,
                statut__in=STATUTS_GROUPES_OUVERTS,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related(
                "affectation_centre",
                "affectation_centre__immerge",
                "groupe",
                "groupe__section",
            )
            .first()
        )

    @staticmethod
    def existe_ouverte(affectation_centre_id):
        return AffectationGroupeRepository.lister_ouvertes().filter(
            affectation_centre_id=affectation_centre_id,
        ).exists()

    @staticmethod
    def verrouiller_par_ids(affectation_ids):
        ids = _liste_ids(affectation_ids)
        return (
            AffectationGroupe.objects.filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related(
                "affectation_centre",
                "affectation_centre__immerge",
                "affectation_centre__session",
                "affectation_centre__centre",
                "groupe",
                "groupe__section",
            )
            .order_by("id")
        )

    @staticmethod
    def compter_par_groupe_et_statuts(
        *,
        session_id,
        centre_id,
        statuts=None,
    ):
        statuts = _liste_statuts(
            statuts,
            STATUTS_GROUPES_OUVERTS,
        )
        return (
            AffectationGroupeRepository.non_supprimees()
            .filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
                statut__in=statuts,
            )
            .values("groupe_id")
            .annotate(total=Count("id"))
            .order_by("groupe_id")
        )

    @staticmethod
    def compter_par_section_et_statuts(
        *,
        session_id,
        centre_id,
        statuts=None,
    ):
        statuts = _liste_statuts(
            statuts,
            STATUTS_GROUPES_OUVERTS,
        )
        return (
            AffectationGroupeRepository.non_supprimees()
            .filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
                statut__in=statuts,
            )
            .values("groupe__section_id")
            .annotate(total=Count("id"))
            .order_by("groupe__section_id")
        )

    @staticmethod
    def compter_ouvertes_centre(*, session_id, centre_id):
        return AffectationGroupeRepository.lister_ouvertes().filter(
            affectation_centre__session_id=session_id,
            affectation_centre__centre_id=centre_id,
        ).count()

    @staticmethod
    def creer(**donnees):
        affectation = AffectationGroupe(**donnees)
        affectation.full_clean()
        affectation.save()
        return affectation

    @staticmethod
    def creer_en_lot(objets, *, batch_size=1000):
        objets = list(objets)
        if not objets:
            return []
        return AffectationGroupe.objects.bulk_create(
            objets,
            batch_size=batch_size,
        )

    @staticmethod
    def mettre_a_jour_en_lot(
        objets,
        champs,
        *,
        batch_size=1000,
    ):
        objets = list(objets)
        if not objets:
            return 0
        AffectationGroupe.objects.bulk_update(
            objets,
            champs,
            batch_size=batch_size,
        )
        return len(objets)


class DortoirRepository:
    """Requêtes sur les dortoirs physiques d'un centre."""

    @staticmethod
    def base_queryset():
        return Dortoir.objects.select_related(
            "centre",
            "centre__region",
        )

    @staticmethod
    def actifs():
        return DortoirRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def lister():
        return DortoirRepository.actifs().order_by(
            "centre__nom",
            "nom",
            "id",
        )

    @staticmethod
    def lister_actifs():
        return DortoirRepository.actifs().filter(
            statut=Dortoir.Statut.ACTIF,
            centre__deleted_at__isnull=True,
            centre__statut=CentreImmersion.Statut.ACTIF,
        ).order_by("centre__nom", "nom", "id")

    @staticmethod
    def filtrer(
        *,
        centre_id=None,
        region_id=None,
        sexe_dortoir=None,
        statut=None,
        recherche=None,
    ):
        queryset = DortoirRepository.actifs()

        if centre_id is not None:
            queryset = queryset.filter(centre_id=centre_id)
        if region_id is not None:
            queryset = queryset.filter(centre__region_id=region_id)
        if sexe_dortoir:
            queryset = queryset.filter(sexe_dortoir=sexe_dortoir)
        if statut:
            queryset = queryset.filter(statut=statut)
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(nom__icontains=recherche)
                | Q(centre__code__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
            )

        return queryset.order_by("centre__nom", "nom", "id")

    @staticmethod
    def lister_par_centre(centre_id):
        return DortoirRepository.lister_actifs().filter(
            centre_id=centre_id,
        )

    @staticmethod
    def lister_donnees_algorithme(centre_id):
        return DortoirRepository.lister_par_centre(
            centre_id,
        ).values(
            "id",
            "centre_id",
            "nom",
            "capacite",
            "sexe_dortoir",
        )

    @staticmethod
    def capacite_totale_par_centre(centre_id):
        resultat = DortoirRepository.lister_par_centre(
            centre_id,
        ).aggregate(
            total=Coalesce(Sum("capacite"), Value(0)),
        )
        return int(resultat["total"] or 0)

    @staticmethod
    def get_by_id(dortoir_id):
        return DortoirRepository.actifs().get(id=dortoir_id)

    @staticmethod
    def get_by_id_pour_update(dortoir_id):
        return (
            Dortoir.objects.filter(
                id=dortoir_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related("centre", "centre__region")
            .get()
        )

    @staticmethod
    def verrouiller_par_ids(dortoir_ids):
        ids = _liste_ids(dortoir_ids)
        return (
            Dortoir.objects.filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def verrouiller_par_centre(centre_id):
        return (
            Dortoir.objects.filter(
                centre_id=centre_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def existe_nom(centre_id, nom, *, exclure_id=None):
        queryset = DortoirRepository.actifs().filter(
            centre_id=centre_id,
            nom=nom,
        )
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def creer(**donnees):
        dortoir = Dortoir(**donnees)
        dortoir.full_clean()
        dortoir.save()
        return dortoir

    @staticmethod
    def sauvegarder(dortoir, *, update_fields=None):
        dortoir.full_clean()
        dortoir.save(update_fields=update_fields)
        return dortoir


class LitRepository:
    """Requêtes sur les lits physiques et leur disponibilité technique."""

    @staticmethod
    def base_queryset():
        return Lit.objects.select_related(
            "dortoir",
            "dortoir__centre",
            "dortoir__centre__region",
        )

    @staticmethod
    def actifs():
        return LitRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def lister():
        return LitRepository.actifs().order_by(
            "dortoir__nom",
            "numero_lit",
            "id",
        )

    @staticmethod
    def lister_utilisables():
        return LitRepository.actifs().filter(
            statut=Lit.Statut.DISPONIBLE,
            dortoir__deleted_at__isnull=True,
            dortoir__statut=Dortoir.Statut.ACTIF,
            dortoir__centre__deleted_at__isnull=True,
            dortoir__centre__statut=CentreImmersion.Statut.ACTIF,
        ).order_by(
            "dortoir__nom",
            "numero_lit",
            "id",
        )

    @staticmethod
    def compter_exploitables_par_centre(centre_id):
        return LitRepository.lister_utilisables().filter(
            dortoir__centre_id=centre_id,
        ).count()

    @staticmethod
    def filtrer(
        *,
        centre_id=None,
        dortoir_id=None,
        region_id=None,
        sexe_dortoir=None,
        statut=None,
        recherche=None,
    ):
        queryset = LitRepository.actifs()

        if centre_id is not None:
            queryset = queryset.filter(dortoir__centre_id=centre_id)
        if dortoir_id is not None:
            queryset = queryset.filter(dortoir_id=dortoir_id)
        if region_id is not None:
            queryset = queryset.filter(
                dortoir__centre__region_id=region_id,
            )
        if sexe_dortoir:
            queryset = queryset.filter(
                dortoir__sexe_dortoir=sexe_dortoir,
            )
        if statut:
            queryset = queryset.filter(statut=statut)
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(numero_lit__icontains=recherche)
                | Q(dortoir__nom__icontains=recherche)
                | Q(dortoir__centre__code__icontains=recherche)
                | Q(dortoir__centre__nom__icontains=recherche)
            )

        return queryset.order_by(
            "dortoir__nom",
            "numero_lit",
            "id",
        )

    @staticmethod
    def lister_utilisables_sans_attribution_ouverte(
        *,
        centre_id,
        sexe_dortoir=None,
    ):
        attribution_ouverte = AttributionLit.objects.filter(
            lit_id=OuterRef("pk"),
            statut__in=STATUTS_LITS_OUVERTS,
            deleted_at__isnull=True,
        )
        queryset = (
            LitRepository.lister_utilisables()
            .filter(dortoir__centre_id=centre_id)
            .annotate(
                possede_attribution_ouverte=Exists(
                    attribution_ouverte
                )
            )
            .filter(possede_attribution_ouverte=False)
        )
        if sexe_dortoir:
            queryset = queryset.filter(
                dortoir__sexe_dortoir=sexe_dortoir,
            )
        return queryset.order_by(
            "dortoir_id",
            "numero_lit",
            "id",
        )

    @staticmethod
    def lister_donnees_algorithme(centre_id):
        return LitRepository.lister_utilisables_sans_attribution_ouverte(
            centre_id=centre_id,
        ).values(
            "id",
            "dortoir_id",
            "dortoir__nom",
            "dortoir__sexe_dortoir",
            "dortoir__capacite",
            "numero_lit",
        )

    @staticmethod
    def compter_par_dortoir(
        *,
        centre_id=None,
        utilisables_seulement=False,
    ):
        queryset = (
            LitRepository.lister_utilisables()
            if utilisables_seulement
            else LitRepository.actifs()
        )
        if centre_id is not None:
            queryset = queryset.filter(
                dortoir__centre_id=centre_id,
            )

        return (
            queryset.values("dortoir_id")
            .annotate(total=Count("id"))
            .order_by("dortoir_id")
        )

    @staticmethod
    def get_by_id(lit_id):
        return LitRepository.actifs().get(id=lit_id)

    @staticmethod
    def get_by_id_pour_update(lit_id):
        return (
            Lit.objects.filter(
                id=lit_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related(
                "dortoir",
                "dortoir__centre",
                "dortoir__centre__region",
            )
            .get()
        )

    @staticmethod
    def verrouiller_par_ids(lit_ids):
        ids = _liste_ids(lit_ids)
        return (
            Lit.objects.filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def verrouiller_utilisables_par_centre(centre_id):
        return (
            Lit.objects.filter(
                dortoir__centre_id=centre_id,
                deleted_at__isnull=True,
                statut=Lit.Statut.DISPONIBLE,
                dortoir__deleted_at__isnull=True,
                dortoir__statut=Dortoir.Statut.ACTIF,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def existe_numero(
        dortoir_id,
        numero_lit,
        *,
        exclure_id=None,
    ):
        queryset = LitRepository.actifs().filter(
            dortoir_id=dortoir_id,
            numero_lit=numero_lit,
        )
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def creer(**donnees):
        lit = Lit(**donnees)
        lit.full_clean()
        lit.save()
        return lit

    @staticmethod
    def creer_en_lot(objets, *, batch_size=1000):
        objets = list(objets)
        if not objets:
            return []
        return Lit.objects.bulk_create(
            objets,
            batch_size=batch_size,
        )

    @staticmethod
    def mettre_a_jour_en_lot(
        objets,
        champs,
        *,
        batch_size=1000,
    ):
        objets = list(objets)
        if not objets:
            return 0
        Lit.objects.bulk_update(
            objets,
            champs,
            batch_size=batch_size,
        )
        return len(objets)

    @staticmethod
    def sauvegarder(lit, *, update_fields=None):
        lit.full_clean()
        lit.save(update_fields=update_fields)
        return lit


class AttributionLitRepository:
    """Persistance et consultation des attributions de lits."""

    @staticmethod
    def base_queryset():
        return AttributionLit.objects.select_related(
            "affectation_centre",
            "affectation_centre__immerge",
            "affectation_centre__session",
            "affectation_centre__centre",
            "affectation_centre__centre__region",
            "lit",
            "lit__dortoir",
            "attribue_par",
        )

    @staticmethod
    def non_supprimees():
        return AttributionLitRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def lister():
        return AttributionLitRepository.non_supprimees().order_by(
            "-date_attribution",
            "-id",
        )

    @staticmethod
    def lister_ouvertes():
        return AttributionLitRepository.non_supprimees().filter(
            statut__in=STATUTS_LITS_OUVERTS,
        ).order_by("-date_attribution", "-id")

    @staticmethod
    def lister_proposees():
        return AttributionLitRepository.non_supprimees().filter(
            statut=AttributionLit.Statut.PROPOSEE,
        ).order_by("-date_attribution", "-id")

    @staticmethod
    def lister_actives():
        return AttributionLitRepository.non_supprimees().filter(
            statut=AttributionLit.Statut.ACTIVE,
        ).order_by("-date_attribution", "-id")

    @staticmethod
    def lister_a_reorganiser():
        return AttributionLitRepository.non_supprimees().filter(
            statut=AttributionLit.Statut.A_REORGANISER,
        ).order_by("-date_attribution", "-id")

    @staticmethod
    def filtrer(
        *,
        session_id=None,
        centre_id=None,
        region_id=None,
        dortoir_id=None,
        lit_id=None,
        sexe_dortoir=None,
        statut=None,
        affectation_centre_id=None,
        recherche=None,
    ):
        queryset = AttributionLitRepository.non_supprimees()

        if session_id is not None:
            queryset = queryset.filter(
                affectation_centre__session_id=session_id,
            )
        if centre_id is not None:
            queryset = queryset.filter(
                affectation_centre__centre_id=centre_id,
            )
        if region_id is not None:
            queryset = queryset.filter(
                affectation_centre__centre__region_id=region_id,
            )
        if dortoir_id is not None:
            queryset = queryset.filter(lit__dortoir_id=dortoir_id)
        if lit_id is not None:
            queryset = queryset.filter(lit_id=lit_id)
        if sexe_dortoir:
            queryset = queryset.filter(
                lit__dortoir__sexe_dortoir=sexe_dortoir,
            )
        if statut:
            queryset = queryset.filter(statut=statut)
        if affectation_centre_id is not None:
            queryset = queryset.filter(
                affectation_centre_id=affectation_centre_id,
            )
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(
                    affectation_centre__immerge__code_fasoim__icontains=
                    recherche
                )
                | Q(lit__numero_lit__icontains=recherche)
                | Q(lit__dortoir__nom__icontains=recherche)
                | Q(observations__icontains=recherche)
            )

        return queryset.order_by("-date_attribution", "-id")

    @staticmethod
    def get_by_id(attribution_id):
        return AttributionLitRepository.non_supprimees().get(
            id=attribution_id,
        )

    @staticmethod
    def get_ouverte_par_affectation_centre(
        affectation_centre_id,
    ):
        return AttributionLitRepository.lister_ouvertes().filter(
            affectation_centre_id=affectation_centre_id,
        ).first()

    @staticmethod
    def get_ouverte_par_affectation_centre_pour_update(
        affectation_centre_id,
    ):
        return (
            AttributionLit.objects.filter(
                affectation_centre_id=affectation_centre_id,
                statut__in=STATUTS_LITS_OUVERTS,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related(
                "affectation_centre",
                "affectation_centre__immerge",
                "lit",
                "lit__dortoir",
            )
            .first()
        )

    @staticmethod
    def get_ouverte_par_lit_pour_update(lit_id):
        return (
            AttributionLit.objects.filter(
                lit_id=lit_id,
                statut__in=STATUTS_LITS_OUVERTS,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related(
                "affectation_centre",
                "lit",
                "lit__dortoir",
            )
            .first()
        )

    @staticmethod
    def existe_ouverte_affectation_centre(
        affectation_centre_id,
    ):
        return AttributionLitRepository.lister_ouvertes().filter(
            affectation_centre_id=affectation_centre_id,
        ).exists()

    @staticmethod
    def existe_ouverte_lit(lit_id):
        return AttributionLitRepository.lister_ouvertes().filter(
            lit_id=lit_id,
        ).exists()

    @staticmethod
    def verrouiller_par_ids(attribution_ids):
        ids = _liste_ids(attribution_ids)
        return (
            AttributionLit.objects.filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .select_related(
                "affectation_centre",
                "affectation_centre__immerge",
                "affectation_centre__session",
                "affectation_centre__centre",
                "lit",
                "lit__dortoir",
            )
            .order_by("id")
        )

    @staticmethod
    def compter_par_dortoir_et_statuts(
        *,
        session_id,
        centre_id,
        statuts=None,
    ):
        statuts = _liste_statuts(
            statuts,
            STATUTS_LITS_OUVERTS,
        )
        return (
            AttributionLitRepository.non_supprimees()
            .filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
                statut__in=statuts,
            )
            .values("lit__dortoir_id")
            .annotate(total=Count("id"))
            .order_by("lit__dortoir_id")
        )

    @staticmethod
    def compter_ouvertes_centre(*, session_id, centre_id):
        return AttributionLitRepository.lister_ouvertes().filter(
            affectation_centre__session_id=session_id,
            affectation_centre__centre_id=centre_id,
        ).count()

    @staticmethod
    def creer(**donnees):
        attribution = AttributionLit(**donnees)
        attribution.full_clean()
        attribution.save()
        return attribution

    @staticmethod
    def creer_en_lot(objets, *, batch_size=1000):
        objets = list(objets)
        if not objets:
            return []
        return AttributionLit.objects.bulk_create(
            objets,
            batch_size=batch_size,
        )

    @staticmethod
    def mettre_a_jour_en_lot(
        objets,
        champs,
        *,
        batch_size=1000,
    ):
        objets = list(objets)
        if not objets:
            return 0
        AttributionLit.objects.bulk_update(
            objets,
            champs,
            batch_size=batch_size,
        )
        return len(objets)


__all__ = [
    "STATUTS_GROUPES_OUVERTS",
    "STATUTS_LITS_OUVERTS",
    "RegleOrganisationCentreRepository",
    "SectionRepository",
    "GroupeRepository",
    "CandidatsOrganisationRepository",
    "AffectationGroupeRepository",
    "DortoirRepository",
    "LitRepository",
    "AttributionLitRepository",
]
