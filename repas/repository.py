from __future__ import annotations

from django.db.models import Count, F, Q, Sum

from affectations.models import AffectationCentre
from organisation.models import AffectationGroupe, Groupe

from .models import (
    DemandeRavitaillementCentre,
    LigneBesoinDenree,
    RepasJournalier,
    SuiviRepas,
)


class DemandeRavitaillementRepository:
    @staticmethod
    def base_queryset():
        return DemandeRavitaillementCentre.objects.select_related(
            "session", "centre", "centre__region", "soumis_par", "valide_par"
        ).prefetch_related("lignes_denrees")

    @classmethod
    def non_supprimees(cls):
        return cls.base_queryset().filter(deleted_at__isnull=True)

    @classmethod
    def get_by_id(cls, demande_id):
        return cls.non_supprimees().get(id=demande_id)

    @classmethod
    def get_by_id_pour_update(cls, demande_id):
        return (
            DemandeRavitaillementCentre.objects.select_for_update(of=("self",))
            .select_related("session", "centre", "centre__region")
            .get(id=demande_id, deleted_at__isnull=True)
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id=None,
        region_id=None,
        centre_id=None,
        statut=None,
        recherche=None,
    ):
        queryset = cls.non_supprimees()
        if session_id:
            queryset = queryset.filter(session_id=session_id)
        if region_id:
            queryset = queryset.filter(centre__region_id=region_id)
        if centre_id:
            queryset = queryset.filter(centre_id=centre_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(session__code__icontains=recherche)
                | Q(session__nom__icontains=recherche)
                | Q(centre__code__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
            )
        return queryset.order_by("-session__annee", "centre__nom", "-id")

    @staticmethod
    def creer(**donnees):
        objet = DemandeRavitaillementCentre(**donnees)
        objet.save()
        return objet


class LigneBesoinDenreeRepository:
    @staticmethod
    def base_queryset():
        return LigneBesoinDenree.objects.select_related(
            "demande_ravitaillement",
            "demande_ravitaillement__session",
            "demande_ravitaillement__centre",
        )

    @classmethod
    def non_supprimees(cls):
        return cls.base_queryset().filter(deleted_at__isnull=True)

    @classmethod
    def get_by_id(cls, ligne_id):
        return cls.non_supprimees().get(id=ligne_id)

    @classmethod
    def get_by_id_pour_update(cls, ligne_id):
        return (
            LigneBesoinDenree.objects.select_for_update(of=("self",))
            .select_related(
                "demande_ravitaillement",
                "demande_ravitaillement__session",
                "demande_ravitaillement__centre",
            )
            .get(id=ligne_id, deleted_at__isnull=True)
        )

    @classmethod
    def filtrer(cls, *, demande_id=None, statut=None, recherche=None):
        queryset = cls.non_supprimees()
        if demande_id:
            queryset = queryset.filter(demande_ravitaillement_id=demande_id)
        if statut:
            queryset = queryset.filter(statut=statut)
        if recherche:
            queryset = queryset.filter(
                Q(code_denree__icontains=recherche)
                | Q(designation__icontains=recherche)
            )
        return queryset.order_by("designation", "id")

    @classmethod
    def consolider(cls, *, session_id, region_id=None, statut_demande=None):
        queryset = cls.non_supprimees().filter(
            demande_ravitaillement__session_id=session_id,
        )
        if region_id:
            queryset = queryset.filter(
                demande_ravitaillement__centre__region_id=region_id,
            )
        if statut_demande:
            if isinstance(statut_demande, (list, tuple, set)):
                queryset = queryset.filter(
                    demande_ravitaillement__statut__in=statut_demande,
                )
            else:
                queryset = queryset.filter(
                    demande_ravitaillement__statut=statut_demande,
                )
        return list(
            queryset.values(
                "code_denree", "designation", "conditionnement", "unite_base"
            )
            .annotate(
                total_demande=Sum("quantite_demandee"),
                total_valide=Sum("quantite_validee"),
                total_recu=Sum("quantite_recue"),
                nombre_centres=Count(
                    "demande_ravitaillement__centre_id", distinct=True
                ),
            )
            .order_by("designation", "code_denree")
        )


class RepasJournalierRepository:
    @staticmethod
    def base_queryset():
        return RepasJournalier.objects.select_related(
            "demande_ravitaillement",
            "demande_ravitaillement__session",
            "demande_ravitaillement__centre",
            "demande_ravitaillement__centre__region",
            "cree_par",
            "valide_par",
        )

    @classmethod
    def non_supprimes(cls):
        return cls.base_queryset().filter(deleted_at__isnull=True)

    @classmethod
    def get_by_id(cls, repas_id):
        return cls.non_supprimes().get(id=repas_id)

    @classmethod
    def get_by_id_pour_update(cls, repas_id):
        return (
            RepasJournalier.objects.select_for_update(of=("self",))
            .select_related(
                "demande_ravitaillement",
                "demande_ravitaillement__session",
                "demande_ravitaillement__centre",
            )
            .get(id=repas_id, deleted_at__isnull=True)
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id=None,
        region_id=None,
        centre_id=None,
        date_debut=None,
        date_fin=None,
        type_repas=None,
        statut=None,
        statut_controle_sante=None,
        recherche=None,
    ):
        queryset = cls.non_supprimes()
        if session_id:
            queryset = queryset.filter(
                demande_ravitaillement__session_id=session_id
            )
        if region_id:
            queryset = queryset.filter(
                demande_ravitaillement__centre__region_id=region_id
            )
        if centre_id:
            queryset = queryset.filter(
                demande_ravitaillement__centre_id=centre_id
            )
        if date_debut:
            queryset = queryset.filter(date_repas__gte=date_debut)
        if date_fin:
            queryset = queryset.filter(date_repas__lte=date_fin)
        if type_repas:
            queryset = queryset.filter(type_repas=type_repas)
        if statut:
            queryset = queryset.filter(statut=statut)
        if statut_controle_sante:
            queryset = queryset.filter(
                statut_controle_sante=statut_controle_sante
            )
        if recherche:
            queryset = queryset.filter(
                Q(menu_prevu__icontains=recherche)
                | Q(menu_prepare__icontains=recherche)
                | Q(demande_ravitaillement__centre__nom__icontains=recherche)
            )
        return queryset.order_by("-date_repas", "type_repas", "id")

    @classmethod
    def futurs_a_revoir(cls, *, session_id, centre_id, date_reference):
        return cls.non_supprimes().filter(
            demande_ravitaillement__session_id=session_id,
            demande_ravitaillement__centre_id=centre_id,
            date_repas__gte=date_reference,
            statut__in=[
                RepasJournalier.Statut.PLANIFIE,
                RepasJournalier.Statut.VALIDE,
                RepasJournalier.Statut.EN_PREPARATION,
                RepasJournalier.Statut.PREPARE,
            ],
        )

    @classmethod
    def statistiques(cls, **filtres):
        queryset = cls.filtrer(**filtres)
        agr = queryset.aggregate(
            repas_planifies=Count("id"),
            repas_clotures=Count(
                "id", filter=Q(statut=RepasJournalier.Statut.CLOTURE)
            ),
            standards_prevus=Sum("nombre_standard_prevu"),
            standards_prepares=Sum("nombre_standard_prepare"),
        )
        suivis = SuiviRepasRepository.non_supprimes().filter(
            repas_journalier_id__in=queryset.values("id")
        )
        comptages = suivis.filter(type_suivi=SuiviRepas.TypeSuivi.COMPTAGE)
        medicaux = suivis.filter(type_suivi=SuiviRepas.TypeSuivi.MEDICAL)
        agr.update(
            comptages.aggregate(total_ayant_mange=Sum("nombre_ayant_mange"))
        )
        agr["repas_speciaux_conformes"] = medicaux.filter(
            statut_service=SuiviRepas.StatutService.SERVI_CONFORME
        ).count()
        agr["repas_speciaux_non_conformes"] = medicaux.filter(
            statut_service=SuiviRepas.StatutService.SERVI_NON_CONFORME
        ).count()
        agr["repas_speciaux_non_servis"] = medicaux.filter(
            statut_service=SuiviRepas.StatutService.NON_SERVI
        ).count()
        agr["absents"] = medicaux.filter(
            statut_service=SuiviRepas.StatutService.ABSENT
        ).count()
        agr["refus"] = medicaux.filter(
            statut_service=SuiviRepas.StatutService.REFUSE
        ).count()
        servis_speciaux = (
            agr["repas_speciaux_conformes"]
            + agr["repas_speciaux_non_conformes"]
        )
        agr["standards_consommes"] = max(
            0, (agr.get("total_ayant_mange") or 0) - servis_speciaux
        )
        agr["ecart_prevu_consomme"] = max(
            0,
            (agr.get("standards_prevus") or 0)
            - agr["standards_consommes"],
        )
        return {cle: valeur or 0 for cle, valeur in agr.items()}


class SuiviRepasRepository:
    @staticmethod
    def base_queryset():
        return SuiviRepas.objects.select_related(
            "repas_journalier",
            "repas_journalier__demande_ravitaillement",
            "repas_journalier__demande_ravitaillement__session",
            "repas_journalier__demande_ravitaillement__centre",
            "groupe",
            "affectation_centre",
            "affectation_centre__immerge",
            "saisi_par",
        )

    @classmethod
    def non_supprimes(cls):
        return cls.base_queryset().filter(deleted_at__isnull=True)

    @classmethod
    def get_by_id(cls, suivi_id):
        return cls.non_supprimes().get(id=suivi_id)

    @classmethod
    def get_by_id_pour_update(cls, suivi_id):
        return (
            SuiviRepas.objects.select_for_update(of=("self",))
            .select_related(
                "repas_journalier",
                "repas_journalier__demande_ravitaillement",
                "affectation_centre",
            )
            .get(id=suivi_id, deleted_at__isnull=True)
        )

    @classmethod
    def filtrer(
        cls,
        *,
        repas_id=None,
        type_suivi=None,
        groupe_id=None,
        affectation_centre_id=None,
        statut_service=None,
    ):
        queryset = cls.non_supprimes()
        if repas_id:
            queryset = queryset.filter(repas_journalier_id=repas_id)
        if type_suivi:
            queryset = queryset.filter(type_suivi=type_suivi)
        if groupe_id:
            queryset = queryset.filter(groupe_id=groupe_id)
        if affectation_centre_id:
            queryset = queryset.filter(
                affectation_centre_id=affectation_centre_id
            )
        if statut_service:
            queryset = queryset.filter(statut_service=statut_service)
        return queryset.order_by("type_suivi", "groupe__code", "id")

    @classmethod
    def suivis_medicaux(cls, repas_id):
        return cls.non_supprimes().filter(
            repas_journalier_id=repas_id,
            type_suivi=SuiviRepas.TypeSuivi.MEDICAL,
        )

    @classmethod
    def comptages(cls, repas_id):
        return cls.non_supprimes().filter(
            repas_journalier_id=repas_id,
            type_suivi=SuiviRepas.TypeSuivi.COMPTAGE,
        )


class CandidatRepasRepository:
    """Requêtes groupées évitant une requête par immergé."""

    @staticmethod
    def affectations_actives(*, session_id, centre_id):
        return AffectationCentre.objects.select_related("immerge").filter(
            session_id=session_id,
            centre_id=centre_id,
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
            immerge__deleted_at__isnull=True,
        )

    @classmethod
    def effectif_actif(cls, *, session_id, centre_id):
        return cls.affectations_actives(
            session_id=session_id, centre_id=centre_id
        ).count()

    @staticmethod
    def groupes_et_effectifs(*, session_id, centre_id):
        lignes = list(
            AffectationGroupe.objects.filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
                affectation_centre__statut=AffectationCentre.Statut.ACTIVE,
                affectation_centre__deleted_at__isnull=True,
                statut=AffectationGroupe.Statut.ACTIVE,
                deleted_at__isnull=True,
                groupe__deleted_at__isnull=True,
            )
            .values("groupe_id")
            .annotate(effectif=Count("affectation_centre_id"))
            .order_by("groupe_id")
        )
        if not lignes:
            return []
        groupes = Groupe.objects.in_bulk(ligne["groupe_id"] for ligne in lignes)
        return [
            {"groupe": groupes[ligne["groupe_id"]], "effectif": ligne["effectif"]}
            for ligne in lignes
        ]
