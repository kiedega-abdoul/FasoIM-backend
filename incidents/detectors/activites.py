from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, F, Q
from django.utils import timezone

from activites.models import Evaluation, Note, Presence, Seance
from affectations.models import AffectationCentre
from organisation.models import AffectationGroupe
from sessions_app.models import SessionImmersion

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "ACT_SEANCE_SANS_FORMATEUR",
    "ACT_SEANCE_NON_TERMINEE",
    "ACT_FEUILLE_PRESENCE_NON_CLOTUREE",
    "ACT_PRESENCES_INCOMPLETES",
    "ACT_EVALUATION_CLOTUREE_NOTES_MANQUANTES",
    "ACT_NOTE_HORS_BAREME",
    "ACT_ABSENCES_RETARDS_REPETES",
)


def _taille_lot():
    return int(getattr(settings, "INCIDENTS_TAILLE_LOT_SCAN", getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500)))


def _seance_est_passee(seance, maintenant):
    fin_naive = datetime.combine(seance.date_seance, seance.heure_fin)
    fin = timezone.make_aware(fin_naive, timezone.get_current_timezone())
    return fin < maintenant


def _affectations_attendues_seance(seance):
    base = AffectationCentre.objects.filter(
        session_id=seance.session_id,
        centre_id=seance.centre_id,
        statut=AffectationCentre.Statut.ACTIVE,
        deleted_at__isnull=True,
    )
    if seance.groupe_id:
        return base.filter(
            affectations_groupes__groupe_id=seance.groupe_id,
            affectations_groupes__statut=AffectationGroupe.Statut.ACTIVE,
            affectations_groupes__deleted_at__isnull=True,
        )
    if seance.section_id:
        return base.filter(
            affectations_groupes__groupe__section_id=seance.section_id,
            affectations_groupes__statut=AffectationGroupe.Statut.ACTIVE,
            affectations_groupes__deleted_at__isnull=True,
        )
    return base


def detecter():
    maintenant = timezone.now()
    taille_lot = _taille_lot()
    seances = Seance.objects.filter(
        session__statut__in=[
            SessionImmersion.Statut.EN_PREPARATION,
            SessionImmersion.Statut.EN_COURS,
        ],
        deleted_at__isnull=True,
    ).select_related("session", "centre", "section", "groupe").iterator(chunk_size=taille_lot)

    for seance in seances:
        if seance.statut in {Seance.Statut.PLANIFIEE, Seance.Statut.EN_COURS} and not seance.formateur_id:
            yield Anomalie(
                code="ACT_SEANCE_SANS_FORMATEUR",
                cle=f"ACT_SEANCE_SANS_FORMATEUR:{seance.id}",
                titre="Séance sans formateur",
                description="Une séance planifiée ou en cours ne possède aucun formateur affecté.",
                categorie=AlerteIncident.Categorie.ACTIVITE,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=seance.session_id,
                centre_id=seance.centre_id,
                module_source="activites",
                modele_source="Seance",
                objet_source_id=seance.id,
                est_bloquante=seance.statut == Seance.Statut.EN_COURS,
            )

        passee = _seance_est_passee(seance, maintenant)
        if passee and seance.statut in {
            Seance.Statut.BROUILLON,
            Seance.Statut.PLANIFIEE,
            Seance.Statut.EN_COURS,
        }:
            yield Anomalie(
                code="ACT_SEANCE_NON_TERMINEE",
                cle=f"ACT_SEANCE_NON_TERMINEE:{seance.id}",
                titre="Séance passée non terminée",
                description="L'heure de fin est dépassée mais la séance n'est ni terminée, reportée ni annulée.",
                categorie=AlerteIncident.Categorie.ACTIVITE,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=seance.session_id,
                centre_id=seance.centre_id,
                module_source="activites",
                modele_source="Seance",
                objet_source_id=seance.id,
            )

        if passee and seance.statut != Seance.Statut.ANNULEE and seance.statut_feuille_presence != Seance.StatutFeuillePresence.CLOTUREE:
            yield Anomalie(
                code="ACT_FEUILLE_PRESENCE_NON_CLOTUREE",
                cle=f"ACT_FEUILLE_PRESENCE_NON_CLOTUREE:{seance.id}",
                titre="Feuille de présence non clôturée",
                description="La séance est passée mais sa feuille de présence n'est pas clôturée.",
                categorie=AlerteIncident.Categorie.ACTIVITE,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=seance.session_id,
                centre_id=seance.centre_id,
                module_source="activites",
                modele_source="Seance",
                objet_source_id=seance.id,
                est_bloquante=True,
            )

        if seance.statut_feuille_presence in {
            Seance.StatutFeuillePresence.VALIDEE,
            Seance.StatutFeuillePresence.CLOTUREE,
        }:
            attendues = _affectations_attendues_seance(seance).distinct().count()
            saisies = Presence.objects.filter(
                seance_id=seance.id,
                deleted_at__isnull=True,
            ).values("affectation_centre_id").distinct().count()
            if saisies < attendues:
                yield Anomalie(
                    code="ACT_PRESENCES_INCOMPLETES",
                    cle=f"ACT_PRESENCES_INCOMPLETES:{seance.id}",
                    titre="Présences incomplètes sur une séance validée",
                    description=f"La feuille contient {saisies} pointage(s) pour {attendues} immergé(s) attendu(s).",
                    categorie=AlerteIncident.Categorie.ACTIVITE,
                    gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                    type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                    session_id=seance.session_id,
                    centre_id=seance.centre_id,
                    module_source="activites",
                    modele_source="Seance",
                    objet_source_id=seance.id,
                    est_bloquante=True,
                    contexte={"attendus": attendues, "saisis": saisies},
                )

    evaluations = Evaluation.objects.filter(
        statut=Evaluation.Statut.CLOTUREE,
        deleted_at__isnull=True,
    ).select_related("session__parametres", "seance").iterator(chunk_size=taille_lot)
    for evaluation in evaluations:
        parametres = getattr(evaluation.session, "parametres", None)
        if not parametres or not parametres.evaluation_active:
            continue
        if evaluation.seance_id:
            attendues_qs = _affectations_attendues_seance(evaluation.seance)
        else:
            attendues_qs = AffectationCentre.objects.filter(
                session_id=evaluation.session_id,
                centre_id=evaluation.centre_id,
                statut=AffectationCentre.Statut.ACTIVE,
                deleted_at__isnull=True,
            )
        attendues = attendues_qs.distinct().count()
        notes = Note.objects.filter(
            evaluation_id=evaluation.id,
            deleted_at__isnull=True,
        ).values("affectation_centre_id").distinct().count()
        if notes < attendues:
            yield Anomalie(
                code="ACT_EVALUATION_CLOTUREE_NOTES_MANQUANTES",
                cle=f"ACT_EVALUATION_CLOTUREE_NOTES_MANQUANTES:{evaluation.id}",
                titre="Évaluation clôturée avec notes manquantes",
                description=f"L'évaluation contient {notes} résultat(s) pour {attendues} immergé(s) attendu(s).",
                categorie=AlerteIncident.Categorie.ACTIVITE,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=evaluation.session_id,
                centre_id=evaluation.centre_id,
                module_source="activites",
                modele_source="Evaluation",
                objet_source_id=evaluation.id,
                est_bloquante=True,
                contexte={"attendus": attendues, "notes": notes},
            )

    for note in Note.objects.filter(
        valeur__isnull=False,
        valeur__gt=F("evaluation__bareme"),
        deleted_at__isnull=True,
    ).select_related("evaluation", "affectation_centre").iterator(chunk_size=taille_lot):
        ac = note.affectation_centre
        yield Anomalie(
            code="ACT_NOTE_HORS_BAREME",
            cle=f"ACT_NOTE_HORS_BAREME:{note.id}",
            titre="Note supérieure au barème",
            description="Une note persistée dépasse le barème de son évaluation.",
            categorie=AlerteIncident.Categorie.ACTIVITE,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=ac.session_id,
            centre_id=ac.centre_id,
            affectation_centre_id=ac.id,
            module_source="activites",
            modele_source="Note",
            objet_source_id=note.id,
            est_bloquante=True,
        )

    depuis = maintenant - timedelta(days=7)
    repetitions = (
        Presence.objects.filter(
            statut_presence__in=[Presence.StatutPresence.ABSENT, Presence.StatutPresence.RETARD],
            date_saisie__gte=depuis,
            deleted_at__isnull=True,
        )
        .values("affectation_centre_id")
        .annotate(total=Count("id"))
        .filter(total__gte=3).iterator(chunk_size=taille_lot)
    )
    for ligne in repetitions:
        ac = AffectationCentre.objects.filter(id=ligne["affectation_centre_id"]).first()
        if not ac:
            continue
        yield Anomalie(
            code="ACT_ABSENCES_RETARDS_REPETES",
            cle=f"ACT_ABSENCES_RETARDS_REPETES:{ac.id}",
            titre="Absences ou retards répétés",
            description=f"L'immergé cumule {ligne['total']} absences ou retards sur les sept derniers jours.",
            categorie=AlerteIncident.Categorie.ACTIVITE,
            gravite=AlerteIncident.NiveauGravite.MOYEN,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=ac.session_id,
            centre_id=ac.centre_id,
            affectation_centre_id=ac.id,
            module_source="activites",
            modele_source="Presence",
            contexte={"occurrences_7_jours": ligne["total"]},
        )
