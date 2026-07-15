from __future__ import annotations

from collections.abc import Iterable

from django.db import models
from django.db.models import Count, Exists, OuterRef, Q, Sum, Value
from django.db.models.functions import Coalesce

from immerges.models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
)

from .models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)


def _liste_ids(valeurs: Iterable[int] | None) -> list[int]:
    """Nettoie une liste d'identifiants sans appliquer de règle métier."""

    if not valeurs:
        return []
    return [int(valeur) for valeur in valeurs if valeur is not None]


def _liste_statuts(
    valeurs: Iterable[str] | None,
    statuts_defaut: Iterable[str],
) -> list[str]:
    """Nettoie une liste de statuts avec plusieurs valeurs par défaut."""

    source = statuts_defaut if valeurs is None else valeurs
    return [str(valeur) for valeur in source if valeur]


STATUTS_REGIONAUX_OUVERTS = (
    AffectationRegionale.Statut.PROPOSEE,
    AffectationRegionale.Statut.ACTIVE,
)
STATUTS_CENTRES_OUVERTS = (
    AffectationCentre.Statut.PROPOSEE,
    AffectationCentre.Statut.ACTIVE,
)


def _limite_lot(limite: int | None) -> int | None:
    """Valide seulement la forme technique de la taille du lot."""

    if limite is None:
        return None
    limite = int(limite)
    if limite <= 0:
        raise ValueError("La taille du lot doit être strictement positive.")
    return limite


class RegionImmersionRepository:
    """Requêtes relatives aux régions d'immersion.

    Aucune région n'est choisie ici. Le service recevra ces données puis
    appliquera la normalisation, la correspondance approximative et les règles
    de capacité.
    """

    @staticmethod
    def base_queryset():
        return RegionImmersion.objects.all()

    @staticmethod
    def actifs():
        return RegionImmersionRepository.base_queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def lister():
        return RegionImmersionRepository.actifs().order_by("nom", "id")

    @staticmethod
    def lister_actives():
        return RegionImmersionRepository.actifs().filter(
            statut=RegionImmersion.Statut.ACTIVE,
        ).order_by("nom", "id")

    @staticmethod
    def lister_donnees_algorithme():
        """Données minimales utilisées pour comparer les noms des régions."""

        return RegionImmersionRepository.lister_actives().values(
            "id",
            "code",
            "nom",
        )

    @staticmethod
    def get_by_id(region_id):
        return RegionImmersionRepository.actifs().get(id=region_id)

    @staticmethod
    def get_by_id_pour_update(region_id):
        return (
            RegionImmersion.objects.filter(
                id=region_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .get()
        )

    @staticmethod
    def get_by_code(code):
        return RegionImmersionRepository.actifs().get(code=code)

    @staticmethod
    def get_by_code_ou_none(code):
        if not code:
            return None
        return RegionImmersionRepository.actifs().filter(code=code).first()

    @staticmethod
    def verrouiller_par_ids(region_ids):
        """Verrouille uniquement les lignes régions demandées par le service."""

        ids = _liste_ids(region_ids)
        return (
            RegionImmersionRepository.actifs()
            .filter(id__in=ids)
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def existe_code(code, *, exclure_id=None):
        queryset = RegionImmersionRepository.actifs().filter(code=code)
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def creer(**donnees):
        region = RegionImmersion(**donnees)
        region.full_clean()
        region.save()
        return region

    @staticmethod
    def sauvegarder(region, *, update_fields=None):
        region.full_clean()
        region.save(update_fields=update_fields)
        return region


class CentreImmersionRepository:
    """Requêtes relatives aux centres.

    Le repository expose les caractéristiques et les agrégats bruts. Il ne
    calcule pas une capacité restante et ne choisit jamais un centre.
    """

    @staticmethod
    def base_queryset():
        return CentreImmersion.objects.select_related("region")

    @staticmethod
    def actifs():
        return CentreImmersionRepository.base_queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def lister():
        return CentreImmersionRepository.actifs().order_by("region__nom", "nom", "id")

    @staticmethod
    def lister_actifs():
        return CentreImmersionRepository.actifs().filter(
            statut=CentreImmersion.Statut.ACTIF,
            region__deleted_at__isnull=True,
            region__statut=RegionImmersion.Statut.ACTIVE,
        ).order_by("region__nom", "nom", "id")

    @staticmethod
    def lister_par_region(region_id):
        return CentreImmersionRepository.lister_actifs().filter(region_id=region_id)

    @staticmethod
    def lister_par_regions(region_ids):
        ids = _liste_ids(region_ids)
        return CentreImmersionRepository.lister_actifs().filter(region_id__in=ids)

    @staticmethod
    def lister_donnees_algorithme(*, region_id=None, region_ids=None):
        """Caractéristiques brutes permettant au service de filtrer les centres."""

        queryset = CentreImmersionRepository.lister_actifs()
        if region_id is not None:
            queryset = queryset.filter(region_id=region_id)
        if region_ids:
            queryset = queryset.filter(region_id__in=_liste_ids(region_ids))

        return queryset.values(
            "id",
            "region_id",
            "code",
            "nom",
            "province",
            "ville",
            "genre",
            "publics_acceptes",
            "niveaux_acceptes",
        )

    @staticmethod
    def capacites_ouvertes_par_region(*, session_id, region_ids=None):
        from organisation.models import RegleOrganisationCentre

        queryset = RegleOrganisationCentre.objects.filter(
            session_id=session_id,
            deleted_at__isnull=True,
            centre__deleted_at__isnull=True,
            centre__statut=CentreImmersion.Statut.ACTIF,
            centre__region__deleted_at__isnull=True,
            centre__region__statut=RegionImmersion.Statut.ACTIVE,
        )
        if region_ids:
            queryset = queryset.filter(centre__region_id__in=_liste_ids(region_ids))
        return (
            queryset.values(region_id=models.F("centre__region_id"))
            .annotate(
                capacite_ouverte_centres=Coalesce(Sum("capacite_ouverte"), Value(0)),
                nombre_centres=Count("centre_id", distinct=True),
            )
            .order_by("region_id")
        )

    @staticmethod
    def capacites_ouvertes_par_centres(*, session_id, centre_ids):
        from organisation.models import RegleOrganisationCentre

        return {
            int(ligne["centre_id"]): int(ligne["capacite_ouverte"] or 0)
            for ligne in RegleOrganisationCentre.objects.filter(
                session_id=session_id,
                centre_id__in=_liste_ids(centre_ids),
                deleted_at__isnull=True,
                centre__deleted_at__isnull=True,
                centre__statut=CentreImmersion.Statut.ACTIF,
            ).values("centre_id", "capacite_ouverte")
        }

    @staticmethod
    def filtrer(
        *,
        region_id=None,
        statut=None,
        genre=None,
        type_immerge=None,
        niveau_examen=None,
        recherche=None,
    ):
        """Filtres de consultation. Le résultat n'est pas un classement métier."""

        queryset = CentreImmersionRepository.actifs()

        if region_id is not None:
            queryset = queryset.filter(region_id=region_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if genre:
            queryset = queryset.filter(genre=genre)
        if type_immerge:
            queryset = queryset.filter(publics_acceptes__contains=[type_immerge])
        if niveau_examen:
            queryset = queryset.filter(niveaux_acceptes__contains=[niveau_examen])
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(code__icontains=recherche)
                | Q(nom__icontains=recherche)
                | Q(province__icontains=recherche)
                | Q(ville__icontains=recherche)
            )

        return queryset.order_by("region__nom", "nom", "id")

    @staticmethod
    def get_by_id(centre_id):
        return CentreImmersionRepository.actifs().get(id=centre_id)

    @staticmethod
    def get_by_id_pour_update(centre_id):
        return (
            CentreImmersion.objects.filter(
                id=centre_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .get()
        )

    @staticmethod
    def get_by_code(code):
        return CentreImmersionRepository.actifs().get(code=code)

    @staticmethod
    def get_by_code_ou_none(code):
        if not code:
            return None
        return CentreImmersionRepository.actifs().filter(code=code).first()

    @staticmethod
    def verrouiller_par_ids(centre_ids):
        ids = _liste_ids(centre_ids)
        return (
            CentreImmersion.objects.filter(
                id__in=ids,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def existe_code(code, *, exclure_id=None):
        queryset = CentreImmersionRepository.actifs().filter(code=code)
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def creer(**donnees):
        centre = CentreImmersion(**donnees)
        centre.full_clean()
        centre.save()
        return centre

    @staticmethod
    def sauvegarder(centre, *, update_fields=None):
        centre.full_clean()
        centre.save(update_fields=update_fields)
        return centre


class CriteresImmergeAffectationRepository:
    """Requêtes de sélection des candidats et de lecture de leurs sources.

    Le responsable pourra demander un lot de N personnes. Le repository prend
    alors les N premiers immergés qui ne possèdent aucune affectation bloquante.
    Le choix de leur région ou de leur centre appartient ensuite au service.
    """

    @staticmethod
    def base_immerges():
        return Immerge.objects.filter(
            deleted_at__isnull=True,
        ).select_related("session")

    @staticmethod
    def filtrer_immerges(
        *,
        session_id=None,
        type_immerge=None,
        statut=None,
        statuts=None,
        immerge_ids=None,
        codes_fasoim=None,
    ):
        queryset = CriteresImmergeAffectationRepository.base_immerges()

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if type_immerge:
            queryset = queryset.filter(type_immerge=type_immerge)
        if statut:
            queryset = queryset.filter(statut=statut)
        if statuts:
            queryset = queryset.filter(statut__in=list(statuts))
        if immerge_ids:
            queryset = queryset.filter(id__in=_liste_ids(immerge_ids))
        if codes_fasoim:
            queryset = queryset.filter(code_fasoim__in=list(codes_fasoim))

        return queryset.order_by("id")

    @staticmethod
    def _queryset_candidats_regionaux(
        *,
        session_id,
        type_immerge=None,
        statut=None,
        statuts=None,
        immerge_ids=None,
        codes_fasoim=None,
        statuts_affectation_bloquants=None,
    ):
        queryset = CriteresImmergeAffectationRepository.filtrer_immerges(
            session_id=session_id,
            type_immerge=type_immerge,
            statut=statut,
            statuts=statuts,
            immerge_ids=immerge_ids,
            codes_fasoim=codes_fasoim,
        )

        statuts_bloquants = _liste_statuts(
            statuts_affectation_bloquants,
            STATUTS_REGIONAUX_OUVERTS,
        )
        affectation_bloquante = AffectationRegionale.objects.filter(
            immerge_id=OuterRef("pk"),
            session_id=session_id,
            statut__in=statuts_bloquants,
            deleted_at__isnull=True,
        )

        return (
            queryset.annotate(
                possede_affectation_regionale_bloquante=Exists(affectation_bloquante),
            )
            .filter(possede_affectation_regionale_bloquante=False)
            .order_by("id")
        )

    @staticmethod
    def candidats_regionaux(
        *,
        session_id,
        limite,
        type_immerge=None,
        statut=None,
        statuts=None,
        immerge_ids=None,
        codes_fasoim=None,
        statuts_affectation_bloquants=None,
    ):
        """Retourne au maximum le nombre demandé par la DGAS."""

        limite = _limite_lot(limite)
        queryset = CriteresImmergeAffectationRepository._queryset_candidats_regionaux(
            session_id=session_id,
            type_immerge=type_immerge,
            statut=statut,
            statuts=statuts,
            immerge_ids=immerge_ids,
            codes_fasoim=codes_fasoim,
            statuts_affectation_bloquants=statuts_affectation_bloquants,
        )
        return queryset[:limite]

    @staticmethod
    def verrouiller_lot_candidats_regionaux(
        *,
        session_id,
        limite,
        type_immerge=None,
        statut=None,
        statuts=None,
        statuts_affectation_bloquants=None,
    ):
        """Sélection transactionnelle d'un lot pour une tâche Celery.

        skip_locked évite que deux workers traitent simultanément les mêmes
        immergés. Cette méthode doit être évaluée dans transaction.atomic().
        """

        limite = _limite_lot(limite)
        queryset = CriteresImmergeAffectationRepository._queryset_candidats_regionaux(
            session_id=session_id,
            type_immerge=type_immerge,
            statut=statut,
            statuts=statuts,
            statuts_affectation_bloquants=statuts_affectation_bloquants,
        )
        return queryset.select_for_update(
            skip_locked=True,
            of=("self",),
        )[:limite]

    @staticmethod
    def compter_candidats_regionaux(
        *,
        session_id,
        statuts_affectation_bloquants=None,
    ):
        return CriteresImmergeAffectationRepository._queryset_candidats_regionaux(
            session_id=session_id,
            statuts_affectation_bloquants=statuts_affectation_bloquants,
        ).count()

    @staticmethod
    def _queryset_candidats_centre(
        *,
        session_id,
        region_id,
        type_immerge=None,
        statut=None,
        statuts=None,
        immerge_ids=None,
        codes_fasoim=None,
        statuts_centre_bloquants=None,
    ):
        queryset = CriteresImmergeAffectationRepository.filtrer_immerges(
            session_id=session_id,
            type_immerge=type_immerge,
            statut=statut,
            statuts=statuts,
            immerge_ids=immerge_ids,
            codes_fasoim=codes_fasoim,
        )

        affectation_regionale_active = AffectationRegionale.objects.filter(
            immerge_id=OuterRef("pk"),
            session_id=session_id,
            region_id=region_id,
            statut=AffectationRegionale.Statut.ACTIVE,
            deleted_at__isnull=True,
        )
        statuts_bloquants = _liste_statuts(
            statuts_centre_bloquants,
            STATUTS_CENTRES_OUVERTS,
        )
        affectation_centre_bloquante = AffectationCentre.objects.filter(
            immerge_id=OuterRef("pk"),
            session_id=session_id,
            statut__in=statuts_bloquants,
            deleted_at__isnull=True,
        )

        return (
            queryset.annotate(
                possede_region_active=Exists(affectation_regionale_active),
                possede_centre_bloquant=Exists(affectation_centre_bloquante),
            )
            .filter(
                possede_region_active=True,
                possede_centre_bloquant=False,
            )
            .order_by("id")
        )

    @staticmethod
    def candidats_centre(
        *,
        session_id,
        region_id,
        limite,
        type_immerge=None,
        statut=None,
        statuts=None,
        immerge_ids=None,
        codes_fasoim=None,
        statuts_centre_bloquants=None,
    ):
        """Retourne au maximum le nombre demandé par le Directeur régional."""

        limite = _limite_lot(limite)
        queryset = CriteresImmergeAffectationRepository._queryset_candidats_centre(
            session_id=session_id,
            region_id=region_id,
            type_immerge=type_immerge,
            statut=statut,
            statuts=statuts,
            immerge_ids=immerge_ids,
            codes_fasoim=codes_fasoim,
            statuts_centre_bloquants=statuts_centre_bloquants,
        )
        return queryset[:limite]

    @staticmethod
    def verrouiller_lot_candidats_centre(
        *,
        session_id,
        region_id,
        limite,
        type_immerge=None,
        statut=None,
        statuts=None,
        statuts_centre_bloquants=None,
    ):
        limite = _limite_lot(limite)
        queryset = CriteresImmergeAffectationRepository._queryset_candidats_centre(
            session_id=session_id,
            region_id=region_id,
            type_immerge=type_immerge,
            statut=statut,
            statuts=statuts,
            statuts_centre_bloquants=statuts_centre_bloquants,
        )
        return queryset.select_for_update(
            skip_locked=True,
            of=("self",),
        )[:limite]

    @staticmethod
    def compter_candidats_centre(
        *,
        session_id,
        region_id,
        statuts_centre_bloquants=None,
    ):
        return CriteresImmergeAffectationRepository._queryset_candidats_centre(
            session_id=session_id,
            region_id=region_id,
            statuts_centre_bloquants=statuts_centre_bloquants,
        ).count()

    @staticmethod
    def sources_examens(origine_ids, *, uniquement_valides=True):
        queryset = ImmergeExamen.objects.filter(
            id__in=_liste_ids(origine_ids),
            deleted_at__isnull=True,
        )
        if uniquement_valides:
            queryset = queryset.filter(
                statut_validation=ImmergeExamen.StatutValidation.VALIDE,
            )
        return queryset.values(
            "id",
            "nom",
            "prenoms",
            "nom_et_prenoms",
            "sexe",
            "date_naissance",
            "numero_pv",
            "type_examen",
            "serie",
            "region_examen",
            "province_examen",
            "centre_examen",
            "etablissement_origine",
            "statut_validation",
        )

    @staticmethod
    def sources_concours(origine_ids, *, uniquement_valides=True):
        queryset = ImmergeConcours.objects.filter(
            id__in=_liste_ids(origine_ids),
            deleted_at__isnull=True,
        )
        if uniquement_valides:
            queryset = queryset.filter(
                statut_validation=ImmergeConcours.StatutValidation.VALIDE,
            )
        return queryset.values(
            "id",
            "nom",
            "prenoms",
            "nom_et_prenoms",
            "sexe",
            "date_naissance",
            "numero_recepisse",
            "specialite",
            "region_composition",
            "province_composition",
            "centre_composition",
            "statut_validation",
        )

    @staticmethod
    def sources_selectionnes(origine_ids, *, uniquement_valides=True):
        queryset = ImmergeSelectionne.objects.filter(
            id__in=_liste_ids(origine_ids),
            deleted_at__isnull=True,
        )
        if uniquement_valides:
            queryset = queryset.filter(
                statut_validation=ImmergeSelectionne.StatutValidation.VALIDE,
            )
        return queryset.values(
            "id",
            "nom",
            "prenoms",
            "nom_et_prenoms",
            "sexe",
            "date_naissance",
            "matricule",
            "reference_selection",
            "structure_origine",
            "region_structure",
            "province_structure",
            "statut_validation",
        )

    @staticmethod
    def sources_volontaires(origine_ids, *, uniquement_acceptes=True):
        queryset = InscriptionVolontaire.objects.filter(
            id__in=_liste_ids(origine_ids),
            deleted_at__isnull=True,
        )
        if uniquement_acceptes:
            queryset = queryset.filter(
                statut_demande=InscriptionVolontaire.StatutDemande.ACCEPTEE,
            )
        return queryset.values(
            "id",
            "nom",
            "prenoms",
            "nom_et_prenoms",
            "sexe",
            "date_naissance",
            "code_suivi",
            "niveau_etude",
            "profession",
            "region_residence",
            "province_residence",
            "commune_residence",
            "statut_demande",
        )


class AffectationRegionaleRepository:
    """Requêtes et écritures élémentaires des affectations régionales."""

    @staticmethod
    def base_queryset():
        return AffectationRegionale.objects.select_related(
            "immerge",
            "session",
            "region",
            "affecte_par",
        )

    @staticmethod
    def actifs():
        return AffectationRegionaleRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def lister():
        return AffectationRegionaleRepository.actifs().order_by(
            "-date_affectation",
            "-id",
        )

    @staticmethod
    def lister_actives():
        return AffectationRegionaleRepository.actifs().filter(
            statut=AffectationRegionale.Statut.ACTIVE,
        )

    @staticmethod
    def lister_proposees():
        return AffectationRegionaleRepository.actifs().filter(
            statut=AffectationRegionale.Statut.PROPOSEE,
        )

    @staticmethod
    def lister_ouvertes():
        return AffectationRegionaleRepository.actifs().filter(
            statut__in=STATUTS_REGIONAUX_OUVERTS,
        )

    @staticmethod
    def filtrer(
        *,
        session_id=None,
        region_id=None,
        statut=None,
        statuts=None,
        type_immerge=None,
        recherche=None,
    ):
        queryset = AffectationRegionaleRepository.actifs()

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if region_id is not None:
            queryset = queryset.filter(region_id=region_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if statuts:
            queryset = queryset.filter(statut__in=list(statuts))
        if type_immerge:
            queryset = queryset.filter(immerge__type_immerge=type_immerge)
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(immerge__code_fasoim__icontains=recherche)
                | Q(region__code__icontains=recherche)
                | Q(region__nom__icontains=recherche)
                | Q(motif__icontains=recherche)
            )

        return queryset.order_by("-date_affectation", "-id")

    @staticmethod
    def get_by_id(affectation_id):
        return AffectationRegionaleRepository.actifs().get(id=affectation_id)

    @staticmethod
    def get_by_id_pour_update(affectation_id):
        return (
            AffectationRegionale.objects.filter(
                id=affectation_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .get()
        )

    @staticmethod
    def get_active_par_immerge(immerge_id):
        return AffectationRegionaleRepository.lister_actives().filter(
            immerge_id=immerge_id,
        ).first()

    @staticmethod
    def get_ouverte_par_immerge(immerge_id):
        return AffectationRegionaleRepository.lister_ouvertes().filter(
            immerge_id=immerge_id,
        ).first()

    @staticmethod
    def get_active_par_immerge_pour_update(immerge_id):
        return (
            AffectationRegionale.objects.filter(
                immerge_id=immerge_id,
                statut=AffectationRegionale.Statut.ACTIVE,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .first()
        )

    @staticmethod
    def get_ouverte_par_immerge_pour_update(immerge_id):
        return (
            AffectationRegionale.objects.filter(
                immerge_id=immerge_id,
                statut__in=STATUTS_REGIONAUX_OUVERTS,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .first()
        )

    @staticmethod
    def lister_par_session(session_id):
        return AffectationRegionaleRepository.lister().filter(session_id=session_id)

    @staticmethod
    def lister_par_region(region_id):
        return AffectationRegionaleRepository.lister().filter(region_id=region_id)

    @staticmethod
    def lister_par_immerge(immerge_id):
        return AffectationRegionaleRepository.base_queryset().filter(
            immerge_id=immerge_id,
        ).order_by("-date_affectation", "-id")

    @staticmethod
    def existe_active(immerge_id):
        return AffectationRegionaleRepository.lister_actives().filter(
            immerge_id=immerge_id,
        ).exists()

    @staticmethod
    def existe_ouverte(immerge_id):
        return AffectationRegionaleRepository.lister_ouvertes().filter(
            immerge_id=immerge_id,
        ).exists()

    @staticmethod
    def lister_par_immerges(immerge_ids, *, statuts=None):
        queryset = AffectationRegionaleRepository.actifs().filter(
            immerge_id__in=_liste_ids(immerge_ids),
        )
        if statuts:
            queryset = queryset.filter(statut__in=list(statuts))
        return queryset.order_by("immerge_id", "-date_affectation", "-id")

    @staticmethod
    def mapping_actives_par_immerges(immerge_ids):
        return AffectationRegionaleRepository.lister_actives().filter(
            immerge_id__in=_liste_ids(immerge_ids),
        ).values(
            "id",
            "immerge_id",
            "session_id",
            "region_id",
        )

    @staticmethod
    def mapping_ouvertes_par_immerges(immerge_ids):
        return AffectationRegionaleRepository.lister_ouvertes().filter(
            immerge_id__in=_liste_ids(immerge_ids),
        ).values(
            "id",
            "immerge_id",
            "session_id",
            "region_id",
            "statut",
        )

    @staticmethod
    def compter_par_region_et_statuts(*, session_id, statuts=None):
        """Agrégat SQL brut des affectations régionales demandées."""

        statuts = _liste_statuts(statuts, STATUTS_REGIONAUX_OUVERTS)
        return (
            AffectationRegionaleRepository.actifs()
            .filter(
                session_id=session_id,
                statut__in=statuts,
            )
            .values("region_id")
            .annotate(total=Count("id"))
            .order_by("region_id")
        )

    @staticmethod
    def ids_immerges_avec_statuts(*, session_id, statuts=None):
        statuts = _liste_statuts(statuts, STATUTS_REGIONAUX_OUVERTS)
        return AffectationRegionaleRepository.actifs().filter(
            session_id=session_id,
            statut__in=statuts,
        ).values_list("immerge_id", flat=True)

    @staticmethod
    def verrouiller_par_ids(affectation_ids):
        return (
            AffectationRegionale.objects.filter(
                id__in=_liste_ids(affectation_ids),
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def creer(**donnees):
        affectation = AffectationRegionale(**donnees)
        affectation.full_clean()
        affectation.save()
        return affectation

    @staticmethod
    def creer_en_lot(affectations, *, batch_size=500):
        return AffectationRegionale.objects.bulk_create(
            affectations,
            batch_size=int(batch_size),
        )

    @staticmethod
    def mettre_a_jour_en_lot(affectations, champs, *, batch_size=500):
        return AffectationRegionale.objects.bulk_update(
            affectations,
            fields=list(champs),
            batch_size=int(batch_size),
        )

    @staticmethod
    def sauvegarder(affectation, *, update_fields=None):
        affectation.full_clean()
        affectation.save(update_fields=update_fields)
        return affectation


class AffectationCentreRepository:
    """Requêtes et écritures élémentaires des affectations aux centres."""

    @staticmethod
    def base_queryset():
        return AffectationCentre.objects.select_related(
            "immerge",
            "session",
            "affectation_regionale",
            "centre",
            "centre__region",
            "affecte_par",
        )

    @staticmethod
    def actifs():
        return AffectationCentreRepository.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @staticmethod
    def lister():
        return AffectationCentreRepository.actifs().order_by(
            "-date_affectation",
            "-id",
        )

    @staticmethod
    def lister_actives():
        return AffectationCentreRepository.actifs().filter(
            statut=AffectationCentre.Statut.ACTIVE,
        )

    @staticmethod
    def lister_proposees():
        return AffectationCentreRepository.actifs().filter(
            statut=AffectationCentre.Statut.PROPOSEE,
        )

    @staticmethod
    def lister_ouvertes():
        return AffectationCentreRepository.actifs().filter(
            statut__in=STATUTS_CENTRES_OUVERTS,
        )

    @staticmethod
    def filtrer(
        *,
        session_id=None,
        region_id=None,
        centre_id=None,
        statut=None,
        statuts=None,
        type_immerge=None,
        recherche=None,
    ):
        queryset = AffectationCentreRepository.actifs()

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if region_id is not None:
            queryset = queryset.filter(centre__region_id=region_id)
        if centre_id is not None:
            queryset = queryset.filter(centre_id=centre_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if statuts:
            queryset = queryset.filter(statut__in=list(statuts))
        if type_immerge:
            queryset = queryset.filter(immerge__type_immerge=type_immerge)
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(immerge__code_fasoim__icontains=recherche)
                | Q(centre__code__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
                | Q(motif__icontains=recherche)
            )

        return queryset.order_by("-date_affectation", "-id")

    @staticmethod
    def get_by_id(affectation_id):
        return AffectationCentreRepository.actifs().get(id=affectation_id)

    @staticmethod
    def get_by_id_pour_update(affectation_id):
        return (
            AffectationCentre.objects.filter(
                id=affectation_id,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .get()
        )

    @staticmethod
    def get_active_par_immerge(immerge_id):
        return AffectationCentreRepository.lister_actives().filter(
            immerge_id=immerge_id,
        ).first()

    @staticmethod
    def get_ouverte_par_immerge(immerge_id):
        return AffectationCentreRepository.lister_ouvertes().filter(
            immerge_id=immerge_id,
        ).first()

    @staticmethod
    def get_active_par_immerge_pour_update(immerge_id):
        return (
            AffectationCentre.objects.filter(
                immerge_id=immerge_id,
                statut=AffectationCentre.Statut.ACTIVE,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .first()
        )

    @staticmethod
    def get_ouverte_par_immerge_pour_update(immerge_id):
        return (
            AffectationCentre.objects.filter(
                immerge_id=immerge_id,
                statut__in=STATUTS_CENTRES_OUVERTS,
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .first()
        )

    @staticmethod
    def lister_par_session(session_id):
        return AffectationCentreRepository.lister().filter(session_id=session_id)

    @staticmethod
    def lister_par_centre(centre_id):
        return AffectationCentreRepository.lister().filter(centre_id=centre_id)

    @staticmethod
    def lister_par_immerge(immerge_id):
        return AffectationCentreRepository.base_queryset().filter(
            immerge_id=immerge_id,
        ).order_by("-date_affectation", "-id")

    @staticmethod
    def existe_active(immerge_id):
        return AffectationCentreRepository.lister_actives().filter(
            immerge_id=immerge_id,
        ).exists()

    @staticmethod
    def existe_ouverte(immerge_id):
        return AffectationCentreRepository.lister_ouvertes().filter(
            immerge_id=immerge_id,
        ).exists()

    @staticmethod
    def lister_par_immerges(immerge_ids, *, statuts=None):
        queryset = AffectationCentreRepository.actifs().filter(
            immerge_id__in=_liste_ids(immerge_ids),
        )
        if statuts:
            queryset = queryset.filter(statut__in=list(statuts))
        return queryset.order_by("immerge_id", "-date_affectation", "-id")

    @staticmethod
    def compter_par_centre_et_statuts(
        *,
        session_id,
        statuts=None,
        region_id=None,
    ):
        """Agrégat SQL brut des affectations centre demandées."""

        statuts = _liste_statuts(statuts, STATUTS_CENTRES_OUVERTS)
        queryset = AffectationCentreRepository.actifs().filter(
            session_id=session_id,
            statut__in=statuts,
        )
        if region_id is not None:
            queryset = queryset.filter(centre__region_id=region_id)

        return (
            queryset.values("centre_id")
            .annotate(total=Count("id"))
            .order_by("centre_id")
        )

    @staticmethod
    def ids_immerges_avec_statuts(*, session_id, statuts=None):
        statuts = _liste_statuts(statuts, STATUTS_CENTRES_OUVERTS)
        return AffectationCentreRepository.actifs().filter(
            session_id=session_id,
            statut__in=statuts,
        ).values_list("immerge_id", flat=True)

    @staticmethod
    def verrouiller_par_ids(affectation_ids):
        return (
            AffectationCentre.objects.filter(
                id__in=_liste_ids(affectation_ids),
                deleted_at__isnull=True,
            )
            .select_for_update(of=("self",))
            .order_by("id")
        )

    @staticmethod
    def creer(**donnees):
        affectation = AffectationCentre(**donnees)
        affectation.full_clean()
        affectation.save()
        return affectation

    @staticmethod
    def creer_en_lot(affectations, *, batch_size=500):
        return AffectationCentre.objects.bulk_create(
            affectations,
            batch_size=int(batch_size),
        )

    @staticmethod
    def mettre_a_jour_en_lot(affectations, champs, *, batch_size=500):
        return AffectationCentre.objects.bulk_update(
            affectations,
            fields=list(champs),
            batch_size=int(batch_size),
        )

    @staticmethod
    def sauvegarder(affectation, *, update_fields=None):
        affectation.full_clean()
        affectation.save(update_fields=update_fields)
        return affectation
