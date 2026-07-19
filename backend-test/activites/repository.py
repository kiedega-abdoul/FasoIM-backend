from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from affectations.models import AffectationCentre
from organisation.models import AffectationGroupe

from .models import (
    Evaluation,
    ModuleActivite,
    Note,
    Presence,
    Seance,
)


class ModuleActiviteRepository:
    """Requêtes et persistance du catalogue des activités."""

    @staticmethod
    def base_queryset():
        return ModuleActivite.objects.all()

    @classmethod
    def non_supprimes(cls):
        return cls.base_queryset().filter(deleted_at__isnull=True)

    @classmethod
    def actifs(cls):
        return cls.non_supprimes().filter(
            statut=ModuleActivite.Statut.ACTIF,
        )

    @classmethod
    def get_by_id(cls, module_id: int):
        return cls.non_supprimes().get(id=module_id)

    @classmethod
    def get_by_id_pour_update(cls, module_id: int):
        return ModuleActivite.objects.select_for_update().get(
            id=module_id,
            deleted_at__isnull=True,
        )

    @classmethod
    def filtrer(
        cls,
        *,
        categorie=None,
        statut=None,
        recherche=None,
    ):
        queryset = cls.non_supprimes()

        if categorie:
            queryset = queryset.filter(categorie=categorie)

        if statut:
            queryset = queryset.filter(statut=statut)

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(code__icontains=recherche)
                | Q(titre__icontains=recherche)
                | Q(description__icontains=recherche)
            )

        return queryset.order_by(
            "ordre",
            "categorie",
            "titre",
            "id",
        )

    @classmethod
    def existe_doublon(
        cls,
        *,
        code,
        titre,
        categorie,
        exclure_id=None,
    ):
        queryset = cls.non_supprimes().filter(
            Q(code__iexact=str(code).strip())
            | Q(
                titre__iexact=str(titre).strip(),
                categorie=categorie,
            )
        )

        if exclure_id:
            queryset = queryset.exclude(id=exclure_id)

        return queryset.exists()

    @staticmethod
    def creer(**donnees):
        module = ModuleActivite(**donnees)
        module.save()
        return module

    @staticmethod
    def sauvegarder(module, *, update_fields=None):
        module.save(update_fields=update_fields)
        return module

    @staticmethod
    def possede_seances(module_id: int):
        return Seance.objects.filter(
            module_activite_id=module_id,
            deleted_at__isnull=True,
        ).exists()


class SeanceRepository:
    """Requêtes et persistance des séances planifiées."""

    STATUTS_OCCUPANT_PLANNING = {
        Seance.Statut.BROUILLON,
        Seance.Statut.PLANIFIEE,
        Seance.Statut.EN_COURS,
    }

    @staticmethod
    def base_queryset():
        return Seance.objects.select_related(
            "module_activite",
            "session",
            "session__parametres",
            "centre",
            "centre__region",
            "section",
            "groupe",
            "groupe__section",
            "formateur",
            "presences_validees_par",
        )

    @classmethod
    def non_supprimees(cls):
        return cls.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @classmethod
    def actives(cls):
        return cls.non_supprimees().exclude(
            statut=Seance.Statut.ANNULEE,
        )

    @classmethod
    def get_by_id(cls, seance_id: int):
        return cls.non_supprimees().get(id=seance_id)

    @classmethod
    def get_by_id_pour_update(cls, seance_id: int):
        return (
            Seance.objects.select_for_update(of=("self",))
            .select_related(
                "module_activite",
                "session",
                "session__parametres",
                "centre",
                "centre__region",
                "section",
                "groupe",
                "groupe__section",
                "formateur",
                "presences_validees_par",
            )
            .get(
                id=seance_id,
                deleted_at__isnull=True,
            )
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id=None,
        centre_id=None,
        section_id=None,
        groupe_id=None,
        module_activite_id=None,
        formateur_id=None,
        statut=None,
        statut_feuille_presence=None,
        date_debut=None,
        date_fin=None,
        recherche=None,
    ):
        queryset = cls.non_supprimees()

        if session_id:
            queryset = queryset.filter(session_id=session_id)

        if centre_id:
            queryset = queryset.filter(centre_id=centre_id)

        if section_id:
            queryset = queryset.filter(
                Q(section_id=section_id)
                | Q(groupe__section_id=section_id)
            )

        if groupe_id:
            queryset = queryset.filter(groupe_id=groupe_id)

        if module_activite_id:
            queryset = queryset.filter(
                module_activite_id=module_activite_id,
            )

        if formateur_id:
            queryset = queryset.filter(
                formateur_id=formateur_id,
            )

        if statut:
            queryset = queryset.filter(statut=statut)

        if statut_feuille_presence:
            queryset = queryset.filter(
                statut_feuille_presence=(
                    statut_feuille_presence
                )
            )

        if date_debut:
            queryset = queryset.filter(
                date_seance__gte=date_debut,
            )

        if date_fin:
            queryset = queryset.filter(
                date_seance__lte=date_fin,
            )

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(titre__icontains=recherche)
                | Q(
                    module_activite__titre__icontains=(
                        recherche
                    )
                )
                | Q(
                    module_activite__code__icontains=(
                        recherche
                    )
                )
                | Q(lieu__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
                | Q(section__nom__icontains=recherche)
                | Q(groupe__nom__icontains=recherche)
            )

        return queryset.order_by(
            "date_seance",
            "heure_debut",
            "centre_id",
            "id",
        )

    @classmethod
    def planning_formateur(
        cls,
        *,
        formateur_id: int,
        date_debut=None,
        date_fin=None,
    ):
        return cls.filtrer(
            formateur_id=formateur_id,
            date_debut=date_debut,
            date_fin=date_fin,
        ).exclude(statut=Seance.Statut.REPORTEE)

    @classmethod
    def _base_chevauchement(
        cls,
        *,
        date_seance,
        heure_debut,
        heure_fin,
        exclure_id=None,
    ):
        queryset = cls.non_supprimees().filter(
            statut__in=cls.STATUTS_OCCUPANT_PLANNING,
            date_seance=date_seance,
            heure_debut__lt=heure_fin,
            heure_fin__gt=heure_debut,
        )

        if exclure_id:
            queryset = queryset.exclude(id=exclure_id)

        return queryset

    @classmethod
    def chevauchement_formateur(
        cls,
        *,
        formateur_id,
        date_seance,
        heure_debut,
        heure_fin,
        exclure_id=None,
    ):
        if not formateur_id:
            return None

        return (
            cls._base_chevauchement(
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                exclure_id=exclure_id,
            )
            .filter(formateur_id=formateur_id)
            .first()
        )

    @classmethod
    def chevauchement_cible(
        cls,
        *,
        session_id,
        centre_id,
        date_seance,
        heure_debut,
        heure_fin,
        section_id=None,
        groupe_id=None,
        groupe_section_id=None,
        exclure_id=None,
    ):
        queryset = cls._base_chevauchement(
            date_seance=date_seance,
            heure_debut=heure_debut,
            heure_fin=heure_fin,
            exclure_id=exclure_id,
        ).filter(
            session_id=session_id,
            centre_id=centre_id,
        )

        cible_centre = Q(
            section__isnull=True,
            groupe__isnull=True,
        )

        if groupe_id:
            cible = (
                cible_centre
                | Q(groupe_id=groupe_id)
                | Q(
                    section_id=groupe_section_id,
                    groupe__isnull=True,
                )
            )
            return queryset.filter(cible).first()

        if section_id:
            cible = (
                cible_centre
                | Q(
                    section_id=section_id,
                    groupe__isnull=True,
                )
                | Q(groupe__section_id=section_id)
            )
            return queryset.filter(cible).first()

        return queryset.first()

    @staticmethod
    def creer(**donnees):
        seance = Seance(**donnees)
        seance.save()
        return seance

    @staticmethod
    def sauvegarder(seance, *, update_fields=None):
        seance.save(update_fields=update_fields)
        return seance

    @staticmethod
    def possede_presences(seance_id: int):
        return Presence.objects.filter(
            seance_id=seance_id,
            deleted_at__isnull=True,
        ).exists()


class CandidatActiviteRepository:
    """Affectations centre appartenant à la cible d'une séance."""

    @staticmethod
    def base_queryset():
        return AffectationCentre.objects.select_related(
            "immerge",
            "session",
            "session__parametres",
            "centre",
            "centre__region",
            "affectation_regionale",
        ).filter(
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        )

    @classmethod
    def pour_seance(cls, seance):
        queryset = cls.base_queryset().filter(
            session_id=seance.session_id,
            centre_id=seance.centre_id,
        )

        if seance.groupe_id:
            queryset = queryset.filter(
                affectations_groupes__groupe_id=(
                    seance.groupe_id
                ),
                affectations_groupes__statut=(
                    AffectationGroupe.Statut.ACTIVE
                ),
                affectations_groupes__deleted_at__isnull=True,
            )

        elif seance.section_id:
            queryset = queryset.filter(
                affectations_groupes__groupe__section_id=(
                    seance.section_id
                ),
                affectations_groupes__statut=(
                    AffectationGroupe.Statut.ACTIVE
                ),
                affectations_groupes__deleted_at__isnull=True,
            )

        return queryset.distinct().order_by(
            "immerge__code_fasoim",
            "id",
        )

    @classmethod
    def pour_evaluation(cls, evaluation):
        if evaluation.seance_id:
            return cls.pour_seance(evaluation.seance)

        return cls.base_queryset().filter(
            session_id=evaluation.session_id,
            centre_id=evaluation.centre_id,
        ).order_by(
            "immerge__code_fasoim",
            "id",
        )

    @classmethod
    def appartient_a_seance(
        cls,
        *,
        seance,
        affectation_centre_id,
    ):
        return cls.pour_seance(seance).filter(
            id=affectation_centre_id,
        ).exists()

    @classmethod
    def appartient_a_evaluation(
        cls,
        *,
        evaluation,
        affectation_centre_id,
    ):
        return cls.pour_evaluation(evaluation).filter(
            id=affectation_centre_id,
        ).exists()

    @classmethod
    def ids_pour_seance(cls, seance):
        return list(
            cls.pour_seance(seance).values_list(
                "id",
                flat=True,
            )
        )

    @classmethod
    def ids_pour_evaluation(cls, evaluation):
        return list(
            cls.pour_evaluation(evaluation).values_list(
                "id",
                flat=True,
            )
        )


class PresenceRepository:
    """Requêtes et persistance des présences."""

    @staticmethod
    def base_queryset():
        return Presence.objects.select_related(
            "seance",
            "seance__module_activite",
            "seance__session",
            "seance__centre",
            "affectation_centre",
            "affectation_centre__immerge",
            "saisie_par",
        )

    @classmethod
    def actives(cls):
        return cls.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @classmethod
    def get_by_id(cls, presence_id: int):
        return cls.actives().get(id=presence_id)

    @classmethod
    def get_by_id_pour_update(cls, presence_id: int):
        return (
            Presence.objects.select_for_update(of=("self",))
            .select_related(
                "seance",
                "seance__module_activite",
                "seance__session",
                "seance__centre",
                "affectation_centre",
                "affectation_centre__immerge",
                "saisie_par",
            )
            .get(
                id=presence_id,
                deleted_at__isnull=True,
            )
        )

    @classmethod
    def get_active_par_seance_affectation(
        cls,
        *,
        seance_id,
        affectation_centre_id,
    ):
        return cls.actives().filter(
            seance_id=seance_id,
            affectation_centre_id=affectation_centre_id,
        ).first()

    @classmethod
    def lister_par_seance(cls, seance_id: int):
        return cls.actives().filter(
            seance_id=seance_id,
        ).order_by(
            "affectation_centre__immerge__code_fasoim",
            "id",
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id=None,
        centre_id=None,
        seance_id=None,
        affectation_centre_id=None,
        statut_presence=None,
        date_debut=None,
        date_fin=None,
        recherche=None,
    ):
        queryset = cls.actives()

        if session_id:
            queryset = queryset.filter(
                seance__session_id=session_id,
            )

        if centre_id:
            queryset = queryset.filter(
                seance__centre_id=centre_id,
            )

        if seance_id:
            queryset = queryset.filter(seance_id=seance_id)

        if affectation_centre_id:
            queryset = queryset.filter(
                affectation_centre_id=affectation_centre_id,
            )

        if statut_presence:
            queryset = queryset.filter(
                statut_presence=statut_presence,
            )

        if date_debut:
            queryset = queryset.filter(
                seance__date_seance__gte=date_debut,
            )

        if date_fin:
            queryset = queryset.filter(
                seance__date_seance__lte=date_fin,
            )

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(
                    affectation_centre__immerge__code_fasoim__icontains=(
                        recherche
                    )
                )
                | Q(seance__titre__icontains=recherche)
                | Q(
                    seance__module_activite__titre__icontains=(
                        recherche
                    )
                )
                | Q(observations__icontains=recherche)
            )

        return queryset.order_by(
            "-seance__date_seance",
            "affectation_centre__immerge__code_fasoim",
        )

    @classmethod
    def paires_existantes(
        cls,
        *,
        seance_id,
        affectation_centre_ids,
    ):
        return set(
            cls.actives()
            .filter(
                seance_id=seance_id,
                affectation_centre_id__in=(
                    affectation_centre_ids
                ),
            )
            .values_list(
                "seance_id",
                "affectation_centre_id",
            )
        )

    @staticmethod
    def creer(**donnees):
        presence = Presence(**donnees)
        presence.save()
        return presence

    @staticmethod
    def sauvegarder(presence, *, update_fields=None):
        presence.save(update_fields=update_fields)
        return presence

    @staticmethod
    def creer_en_masse(presences, *, batch_size=500):
        if not presences:
            return []

        return Presence.objects.bulk_create(
            presences,
            batch_size=batch_size,
            ignore_conflicts=True,
        )

    @staticmethod
    def mettre_a_jour_en_masse(
        presences,
        champs,
        *,
        batch_size=500,
    ):
        if not presences:
            return 0

        Presence.objects.bulk_update(
            presences,
            champs,
            batch_size=batch_size,
        )
        return len(presences)

    @classmethod
    def statistiques_seance(cls, seance_id: int):
        return cls.actives().filter(
            seance_id=seance_id,
        ).values("statut_presence").annotate(
            total=Count("id"),
        ).order_by("statut_presence")

    @classmethod
    def pour_taux(
        cls,
        *,
        affectation_centre_id,
        session_id,
        date_debut=None,
        date_fin=None,
    ):
        queryset = cls.actives().filter(
            affectation_centre_id=affectation_centre_id,
            seance__session_id=session_id,
            seance__statut_feuille_presence__in=[
                Seance.StatutFeuillePresence.VALIDEE,
                Seance.StatutFeuillePresence.CLOTUREE,
            ],
        )

        if date_debut:
            queryset = queryset.filter(
                seance__date_seance__gte=date_debut,
            )

        if date_fin:
            queryset = queryset.filter(
                seance__date_seance__lte=date_fin,
            )

        return queryset.order_by(
            "seance__date_seance",
            "seance__heure_debut",
        )


class EvaluationRepository:
    """Requêtes et persistance des évaluations."""

    @staticmethod
    def base_queryset():
        return Evaluation.objects.select_related(
            "session",
            "session__parametres",
            "centre",
            "centre__region",
            "seance",
            "seance__module_activite",
            "created_by",
        )

    @classmethod
    def non_supprimees(cls):
        return cls.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @classmethod
    def actives(cls):
        return cls.non_supprimees().exclude(
            statut=Evaluation.Statut.ANNULEE,
        )

    @classmethod
    def get_by_id(cls, evaluation_id: int):
        return cls.non_supprimees().get(id=evaluation_id)

    @classmethod
    def get_by_id_pour_update(cls, evaluation_id: int):
        return (
            Evaluation.objects.select_for_update(of=("self",))
            .select_related(
                "session",
                "session__parametres",
                "centre",
                "centre__region",
                "seance",
                "seance__module_activite",
                "created_by",
            )
            .get(
                id=evaluation_id,
                deleted_at__isnull=True,
            )
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id=None,
        centre_id=None,
        seance_id=None,
        type_evaluation=None,
        statut=None,
        date_debut=None,
        date_fin=None,
        recherche=None,
    ):
        queryset = cls.non_supprimees()

        if session_id:
            queryset = queryset.filter(session_id=session_id)

        if centre_id:
            queryset = queryset.filter(centre_id=centre_id)

        if seance_id:
            queryset = queryset.filter(seance_id=seance_id)

        if type_evaluation:
            queryset = queryset.filter(
                type_evaluation=type_evaluation,
            )

        if statut:
            queryset = queryset.filter(statut=statut)

        if date_debut:
            queryset = queryset.filter(
                date_evaluation__date__gte=date_debut,
            )

        if date_fin:
            queryset = queryset.filter(
                date_evaluation__date__lte=date_fin,
            )

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(titre__icontains=recherche)
                | Q(
                    seance__module_activite__titre__icontains=(
                        recherche
                    )
                )
                | Q(centre__nom__icontains=recherche)
            )

        return queryset.order_by(
            "date_evaluation",
            "centre_id",
            "id",
        )

    @staticmethod
    def creer(**donnees):
        evaluation = Evaluation(**donnees)
        evaluation.save()
        return evaluation

    @staticmethod
    def sauvegarder(evaluation, *, update_fields=None):
        evaluation.save(update_fields=update_fields)
        return evaluation

    @staticmethod
    def possede_notes(evaluation_id: int):
        return Note.objects.filter(
            evaluation_id=evaluation_id,
            deleted_at__isnull=True,
        ).exists()


class NoteRepository:
    """Requêtes et persistance des notes."""

    @staticmethod
    def base_queryset():
        return Note.objects.select_related(
            "evaluation",
            "evaluation__session",
            "evaluation__centre",
            "evaluation__seance",
            "evaluation__seance__module_activite",
            "affectation_centre",
            "affectation_centre__immerge",
            "saisie_par",
        )

    @classmethod
    def actives(cls):
        return cls.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @classmethod
    def get_by_id(cls, note_id: int):
        return cls.actives().get(id=note_id)

    @classmethod
    def get_by_id_pour_update(cls, note_id: int):
        return (
            Note.objects.select_for_update(of=("self",))
            .select_related(
                "evaluation",
                "evaluation__session",
                "evaluation__centre",
                "evaluation__seance",
                "evaluation__seance__module_activite",
                "affectation_centre",
                "affectation_centre__immerge",
                "saisie_par",
            )
            .get(
                id=note_id,
                deleted_at__isnull=True,
            )
        )

    @classmethod
    def get_active_par_evaluation_affectation(
        cls,
        *,
        evaluation_id,
        affectation_centre_id,
    ):
        return cls.actives().filter(
            evaluation_id=evaluation_id,
            affectation_centre_id=affectation_centre_id,
        ).first()

    @classmethod
    def lister_par_evaluation(cls, evaluation_id: int):
        return cls.actives().filter(
            evaluation_id=evaluation_id,
        ).order_by(
            "affectation_centre__immerge__code_fasoim",
            "id",
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id=None,
        centre_id=None,
        evaluation_id=None,
        affectation_centre_id=None,
        statut_note=None,
        date_debut=None,
        date_fin=None,
        recherche=None,
    ):
        queryset = cls.actives()

        if session_id:
            queryset = queryset.filter(
                evaluation__session_id=session_id,
            )

        if centre_id:
            queryset = queryset.filter(
                evaluation__centre_id=centre_id,
            )

        if evaluation_id:
            queryset = queryset.filter(
                evaluation_id=evaluation_id,
            )

        if affectation_centre_id:
            queryset = queryset.filter(
                affectation_centre_id=affectation_centre_id,
            )

        if statut_note:
            queryset = queryset.filter(
                statut_note=statut_note,
            )

        if date_debut:
            queryset = queryset.filter(
                evaluation__date_evaluation__date__gte=(
                    date_debut
                )
            )

        if date_fin:
            queryset = queryset.filter(
                evaluation__date_evaluation__date__lte=(
                    date_fin
                )
            )

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(
                    affectation_centre__immerge__code_fasoim__icontains=(
                        recherche
                    )
                )
                | Q(evaluation__titre__icontains=recherche)
                | Q(appreciation__icontains=recherche)
                | Q(observations__icontains=recherche)
            )

        return queryset.order_by(
            "-evaluation__date_evaluation",
            "affectation_centre__immerge__code_fasoim",
        )

    @classmethod
    def paires_existantes(
        cls,
        *,
        evaluation_id,
        affectation_centre_ids,
    ):
        return set(
            cls.actives()
            .filter(
                evaluation_id=evaluation_id,
                affectation_centre_id__in=(
                    affectation_centre_ids
                ),
            )
            .values_list(
                "evaluation_id",
                "affectation_centre_id",
            )
        )

    @staticmethod
    def creer(**donnees):
        note = Note(**donnees)
        note.save()
        return note

    @staticmethod
    def sauvegarder(note, *, update_fields=None):
        note.save(update_fields=update_fields)
        return note

    @staticmethod
    def creer_en_masse(notes, *, batch_size=500):
        if not notes:
            return []

        return Note.objects.bulk_create(
            notes,
            batch_size=batch_size,
            ignore_conflicts=True,
        )

    @staticmethod
    def mettre_a_jour_en_masse(
        notes,
        champs,
        *,
        batch_size=500,
    ):
        if not notes:
            return 0

        Note.objects.bulk_update(
            notes,
            champs,
            batch_size=batch_size,
        )
        return len(notes)

    @classmethod
    def statistiques_evaluation(cls, evaluation_id: int):
        return cls.actives().filter(
            evaluation_id=evaluation_id,
        ).values("statut_note").annotate(
            total=Count("id"),
        ).order_by("statut_note")

    @classmethod
    def pour_moyenne(
        cls,
        *,
        affectation_centre_id,
        session_id,
    ):
        return cls.actives().filter(
            affectation_centre_id=affectation_centre_id,
            evaluation__session_id=session_id,
            evaluation__statut=Evaluation.Statut.CLOTUREE,
            statut_note__in=[
                Note.StatutNote.NOTEE,
                Note.StatutNote.ABSENT,
                Note.StatutNote.DISPENSE,
            ],
        ).order_by(
            "evaluation__date_evaluation",
            "evaluation_id",
        )
