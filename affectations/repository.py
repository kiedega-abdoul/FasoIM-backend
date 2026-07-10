from __future__ import annotations

from typing import Iterable

from django.db.models import Count, Q

from immerges.models import Immerge

from .models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)


class RegionImmersionRepository:
    """Accès aux régions d'immersion.

    Le repository ne décide pas qui a le droit d'affecter une région.
    Il fournit seulement des requêtes propres, réutilisables par le service.
    """

    @staticmethod
    def base_queryset():
        return RegionImmersion.objects.all()

    @staticmethod
    def actifs():
        """Retourne les régions non supprimées logiquement."""

        return RegionImmersionRepository.base_queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def lister():
        return RegionImmersionRepository.actifs().order_by("nom")

    @staticmethod
    def lister_actives():
        return RegionImmersionRepository.actifs().filter(
            statut=RegionImmersion.Statut.ACTIVE,
        ).order_by("nom")

    @staticmethod
    def get_by_id(region_id):
        return RegionImmersionRepository.actifs().get(id=region_id)

    @staticmethod
    def get_by_id_pour_update(region_id):
        return (
            RegionImmersionRepository.actifs()
            .select_for_update(of=("self",))
            .get(id=region_id)
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
    def existe_code(code, *, exclure_id=None):
        queryset = RegionImmersionRepository.actifs().filter(code=code)
        if exclure_id:
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
    """Accès aux centres d'immersion.

    Les centres sont les lieux physiques utilisés après l'affectation régionale.
    L'occupation du centre se calcule depuis AffectationCentre, elle n'est pas
    stockée directement dans CentreImmersion pour éviter les incohérences.
    """

    @staticmethod
    def base_queryset():
        return CentreImmersion.objects.select_related("region")

    @staticmethod
    def actifs():
        return CentreImmersionRepository.base_queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def lister():
        return CentreImmersionRepository.actifs().order_by("region__nom", "nom")

    @staticmethod
    def lister_actifs():
        return CentreImmersionRepository.actifs().filter(
            statut=CentreImmersion.Statut.ACTIF,
            region__deleted_at__isnull=True,
            region__statut=RegionImmersion.Statut.ACTIVE,
        ).order_by("region__nom", "nom")

    @staticmethod
    def lister_par_region(region_id):
        return CentreImmersionRepository.lister_actifs().filter(region_id=region_id)

    @staticmethod
    def lister_par_public(type_immerge):
        """Retourne les centres dont le JSON publics_acceptes contient le type demandé."""

        if not type_immerge:
            return CentreImmersionRepository.lister_actifs()
        return CentreImmersionRepository.lister_actifs().filter(publics_acceptes__contains=[type_immerge])

    @staticmethod
    def filtrer(*, region_id=None, statut=None, genre=None, type_immerge=None, recherche=None):
        """Filtre les centres pour les écrans de consultation ou de choix."""

        queryset = CentreImmersionRepository.actifs()

        if region_id:
            queryset = queryset.filter(region_id=region_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if genre:
            queryset = queryset.filter(genre=genre)
        if type_immerge:
            queryset = queryset.filter(publics_acceptes__contains=[type_immerge])
        if recherche:
            queryset = queryset.filter(
                Q(code__icontains=recherche)
                | Q(nom__icontains=recherche)
                | Q(province__icontains=recherche)
                | Q(ville__icontains=recherche)
            )

        return queryset.order_by("region__nom", "nom")

    @staticmethod
    def avec_occupation(queryset=None):
        """Ajoute le nombre d'affectations centre actives à chaque centre."""

        queryset = queryset or CentreImmersionRepository.lister_actifs()
        return queryset.annotate(
            occupation_active=Count(
                "affectations_centres",
                filter=Q(
                    affectations_centres__statut=AffectationCentre.Statut.ACTIVE,
                    affectations_centres__deleted_at__isnull=True,
                ),
                distinct=True,
            )
        )

    @staticmethod
    def nombre_affectations_actives(centre_id):
        return AffectationCentreRepository.lister_actives().filter(centre_id=centre_id).count()

    @staticmethod
    def capacite_restante(centre):
        """Calcule la capacité restante d'un centre."""

        occupation = CentreImmersionRepository.nombre_affectations_actives(centre.id)
        return max((centre.capacite_totale or 0) - occupation, 0)

    @staticmethod
    def centre_a_place(centre, nombre=1):
        return CentreImmersionRepository.capacite_restante(centre) >= nombre

    @staticmethod
    def get_by_id(centre_id):
        return CentreImmersionRepository.actifs().get(id=centre_id)

    @staticmethod
    def get_by_id_pour_update(centre_id):
        return (
            CentreImmersionRepository.actifs()
            .select_for_update(of=("self",))
            .get(id=centre_id)
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
    def existe_code(code, *, exclure_id=None):
        queryset = CentreImmersionRepository.actifs().filter(code=code)
        if exclure_id:
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
    """Construit les listes d'immergés à affecter individuellement ou en masse.

    Les critères viennent des écrans/API : session, type d'immergé, statut,
    liste d'identifiants, liste de codes FasoIM, région déjà affectée, etc.
    Le service décidera ensuite comment créer les affectations.
    """

    @staticmethod
    def base_immerges():
        return Immerge.objects.filter(deleted_at__isnull=True).select_related("session")

    @staticmethod
    def filtrer_immerges(
        *,
        session_id=None,
        type_immerge=None,
        statut=None,
        immerge_ids: Iterable[int] | None = None,
        codes_fasoim: Iterable[str] | None = None,
        exclure_affectation_regionale_active=False,
        exclure_affectation_centre_active=False,
        region_id=None,
        centre_id=None,
    ):
        """Retourne une queryset d'immergés selon les critères fournis."""

        queryset = CriteresImmergeAffectationRepository.base_immerges()

        if session_id:
            queryset = queryset.filter(session_id=session_id)
        if type_immerge:
            queryset = queryset.filter(type_immerge=type_immerge)
        if statut:
            queryset = queryset.filter(statut=statut)
        if immerge_ids:
            queryset = queryset.filter(id__in=list(immerge_ids))
        if codes_fasoim:
            queryset = queryset.filter(code_fasoim__in=list(codes_fasoim))

        if region_id:
            queryset = queryset.filter(
                affectations_regionales__region_id=region_id,
                affectations_regionales__statut=AffectationRegionale.Statut.ACTIVE,
                affectations_regionales__deleted_at__isnull=True,
            )

        if centre_id:
            queryset = queryset.filter(
                affectations_centres__centre_id=centre_id,
                affectations_centres__statut=AffectationCentre.Statut.ACTIVE,
                affectations_centres__deleted_at__isnull=True,
            )

        if exclure_affectation_regionale_active:
            queryset = queryset.exclude(
                affectations_regionales__statut=AffectationRegionale.Statut.ACTIVE,
                affectations_regionales__deleted_at__isnull=True,
            )

        if exclure_affectation_centre_active:
            queryset = queryset.exclude(
                affectations_centres__statut=AffectationCentre.Statut.ACTIVE,
                affectations_centres__deleted_at__isnull=True,
            )

        return queryset.distinct().order_by("id")

    @staticmethod
    def candidats_regionaux(
        *,
        session_id,
        type_immerge=None,
        statut=None,
        immerge_ids=None,
        codes_fasoim=None,
        exclure_deja_affectes=True,
        limite=None,
    ):
        """Retourne les immergés candidats à une affectation régionale."""

        queryset = CriteresImmergeAffectationRepository.filtrer_immerges(
            session_id=session_id,
            type_immerge=type_immerge,
            statut=statut,
            immerge_ids=immerge_ids,
            codes_fasoim=codes_fasoim,
            exclure_affectation_regionale_active=exclure_deja_affectes,
        )

        if limite:
            return queryset[: int(limite)]
        return queryset

    @staticmethod
    def candidats_centre(
        *,
        session_id,
        region_id,
        type_immerge=None,
        statut=None,
        immerge_ids=None,
        codes_fasoim=None,
        exclure_deja_affectes=True,
        limite=None,
    ):
        """Retourne les immergés d'une région candidats à une affectation centre."""

        queryset = CriteresImmergeAffectationRepository.filtrer_immerges(
            session_id=session_id,
            type_immerge=type_immerge,
            statut=statut,
            immerge_ids=immerge_ids,
            codes_fasoim=codes_fasoim,
            exclure_affectation_centre_active=exclure_deja_affectes,
            region_id=region_id,
        )

        if limite:
            return queryset[: int(limite)]
        return queryset


class AffectationRegionaleRepository:
    """Accès aux affectations régionales des immergés."""

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
        return AffectationRegionaleRepository.base_queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def lister():
        return AffectationRegionaleRepository.actifs().order_by("-date_affectation", "-id")

    @staticmethod
    def lister_actives():
        return AffectationRegionaleRepository.actifs().filter(
            statut=AffectationRegionale.Statut.ACTIVE,
        )

    @staticmethod
    def filtrer(*, session_id=None, region_id=None, statut=None, type_immerge=None, recherche=None):
        queryset = AffectationRegionaleRepository.actifs()

        if session_id:
            queryset = queryset.filter(session_id=session_id)
        if region_id:
            queryset = queryset.filter(region_id=region_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if type_immerge:
            queryset = queryset.filter(immerge__type_immerge=type_immerge)
        if recherche:
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
            AffectationRegionaleRepository.actifs()
            .select_for_update(of=("self",))
            .get(id=affectation_id)
        )

    @staticmethod
    def get_active_par_immerge(immerge_id):
        return AffectationRegionaleRepository.lister_actives().filter(immerge_id=immerge_id).first()

    @staticmethod
    def get_active_par_immerge_pour_update(immerge_id):
        return (
            AffectationRegionaleRepository.lister_actives()
            .select_for_update(of=("self",))
            .filter(immerge_id=immerge_id)
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
        return AffectationRegionaleRepository.base_queryset().filter(immerge_id=immerge_id).order_by("-date_affectation", "-id")

    @staticmethod
    def existe_active(immerge_id):
        return AffectationRegionaleRepository.lister_actives().filter(immerge_id=immerge_id).exists()

    @staticmethod
    def creer(**donnees):
        affectation = AffectationRegionale(**donnees)
        affectation.full_clean()
        affectation.save()
        return affectation

    @staticmethod
    def creer_en_lot(affectations):
        """Insère en masse des affectations déjà construites et validées par le service."""

        return AffectationRegionale.objects.bulk_create(affectations, batch_size=500)

    @staticmethod
    def sauvegarder(affectation, *, update_fields=None):
        affectation.full_clean()
        affectation.save(update_fields=update_fields)
        return affectation

    @staticmethod
    def compter_par_region(session_id=None):
        queryset = AffectationRegionaleRepository.lister_actives()
        if session_id:
            queryset = queryset.filter(session_id=session_id)
        return queryset.values("region_id", "region__code", "region__nom").annotate(total=Count("id")).order_by("region__nom")


class AffectationCentreRepository:
    """Accès aux affectations des immergés vers les centres."""

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
        return AffectationCentreRepository.base_queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def lister():
        return AffectationCentreRepository.actifs().order_by("-date_affectation", "-id")

    @staticmethod
    def lister_actives():
        return AffectationCentreRepository.actifs().filter(statut=AffectationCentre.Statut.ACTIVE)

    @staticmethod
    def filtrer(*, session_id=None, region_id=None, centre_id=None, statut=None, type_immerge=None, recherche=None):
        queryset = AffectationCentreRepository.actifs()

        if session_id:
            queryset = queryset.filter(session_id=session_id)
        if region_id:
            queryset = queryset.filter(centre__region_id=region_id)
        if centre_id:
            queryset = queryset.filter(centre_id=centre_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if type_immerge:
            queryset = queryset.filter(immerge__type_immerge=type_immerge)
        if recherche:
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
            AffectationCentreRepository.actifs()
            .select_for_update(of=("self",))
            .get(id=affectation_id)
        )

    @staticmethod
    def get_active_par_immerge(immerge_id):
        return AffectationCentreRepository.lister_actives().filter(immerge_id=immerge_id).first()

    @staticmethod
    def get_active_par_immerge_pour_update(immerge_id):
        return (
            AffectationCentreRepository.lister_actives()
            .select_for_update(of=("self",))
            .filter(immerge_id=immerge_id)
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
        return AffectationCentreRepository.base_queryset().filter(immerge_id=immerge_id).order_by("-date_affectation", "-id")

    @staticmethod
    def existe_active(immerge_id):
        return AffectationCentreRepository.lister_actives().filter(immerge_id=immerge_id).exists()

    @staticmethod
    def creer(**donnees):
        affectation = AffectationCentre(**donnees)
        affectation.full_clean()
        affectation.save()
        return affectation

    @staticmethod
    def creer_en_lot(affectations):
        """Insère en masse des affectations centre préparées par le service."""

        return AffectationCentre.objects.bulk_create(affectations, batch_size=500)

    @staticmethod
    def sauvegarder(affectation, *, update_fields=None):
        affectation.full_clean()
        affectation.save(update_fields=update_fields)
        return affectation

    @staticmethod
    def compter_par_centre(session_id=None, region_id=None):
        queryset = AffectationCentreRepository.lister_actives()
        if session_id:
            queryset = queryset.filter(session_id=session_id)
        if region_id:
            queryset = queryset.filter(centre__region_id=region_id)
        return queryset.values("centre_id", "centre__code", "centre__nom", "centre__region__nom").annotate(total=Count("id")).order_by("centre__region__nom", "centre__nom")
