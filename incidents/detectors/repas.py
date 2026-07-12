from __future__ import annotations

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from repas.models import (
    DemandeRavitaillementCentre,
    LigneBesoinDenree,
    RepasJournalier,
    SuiviRepas,
)
from sessions_app.models import SessionImmersion

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "REP_DENREES_INSUFFISANTES",
    "REP_REPAS_NON_PREPARE_A_TEMPS",
    "REP_DISTRIBUTION_NON_CLOTUREE",
    "REP_CONTROLE_SANTE_A_REVOIR",
    "REP_PORTIONS_PREPAREES_INSUFFISANTES",
    "REP_SUIVIS_ABSENTS",
    "REP_REPAS_MEDICAL_NON_CONFORME",
)


def _limite():
    return int(getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500))


def _date_heure_repas(repas):
    # Sans heure prévue, le repas n'est considéré en retard qu'à la fin de la
    # journée. Cela évite une fausse alerte dès 00 h 01 pour le jour courant.
    heure = repas.heure_prevue or time(23, 59, 59)
    naive = datetime.combine(repas.date_repas, heure)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def detecter():
    maintenant = timezone.now()
    limite = _limite()

    lignes = LigneBesoinDenree.objects.filter(
        demande_ravitaillement__statut__in=[
            DemandeRavitaillementCentre.Statut.VALIDEE,
            DemandeRavitaillementCentre.Statut.PARTIELLEMENT_RECUE,
            DemandeRavitaillementCentre.Statut.RECUE,
        ],
        demande_ravitaillement__deleted_at__isnull=True,
        statut__in=[
            LigneBesoinDenree.Statut.VALIDEE,
            LigneBesoinDenree.Statut.PARTIELLEMENT_RECUE,
            LigneBesoinDenree.Statut.RECUE,
        ],
        quantite_recue__lt=F("quantite_validee"),
        deleted_at__isnull=True,
    ).select_related("demande_ravitaillement")[:limite]
    for ligne in lignes:
        demande = ligne.demande_ravitaillement
        yield Anomalie(
            code="REP_DENREES_INSUFFISANTES",
            cle=f"REP_DENREES_INSUFFISANTES:{ligne.id}",
            titre=f"Denrée reçue en quantité insuffisante : {ligne.designation}",
            description=(
                f"La quantité reçue ({ligne.quantite_recue}) est inférieure à la quantité validée "
                f"({ligne.quantite_validee})."
            ),
            categorie=AlerteIncident.Categorie.REPAS,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.CENTRE,
            session_id=demande.session_id,
            centre_id=demande.centre_id,
            module_source="repas",
            modele_source="LigneBesoinDenree",
            objet_source_id=ligne.id,
            est_bloquante=True,
        )

    repas_qs = RepasJournalier.objects.filter(
        demande_ravitaillement__session__statut=SessionImmersion.Statut.EN_COURS,
        demande_ravitaillement__session__parametres__repas_active=True,
        demande_ravitaillement__deleted_at__isnull=True,
        deleted_at__isnull=True,
    ).select_related("demande_ravitaillement")[:limite]
    for repas in repas_qs:
        heure = _date_heure_repas(repas)
        passe = heure < maintenant
        largement_passe = heure + timedelta(hours=3) < maintenant

        if passe and repas.statut in {
            RepasJournalier.Statut.BROUILLON,
            RepasJournalier.Statut.PLANIFIE,
            RepasJournalier.Statut.VALIDE,
            RepasJournalier.Statut.EN_PREPARATION,
        }:
            yield Anomalie(
                code="REP_REPAS_NON_PREPARE_A_TEMPS",
                cle=f"REP_REPAS_NON_PREPARE_A_TEMPS:{repas.id}",
                titre="Repas non préparé à l'heure prévue",
                description="L'heure prévue est dépassée mais le repas n'est pas marqué préparé ou distribué.",
                categorie=AlerteIncident.Categorie.REPAS,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=repas.session_id,
                centre_id=repas.centre_id,
                module_source="repas",
                modele_source="RepasJournalier",
                objet_source_id=repas.id,
                est_bloquante=True,
            )

        if largement_passe and repas.statut in {
            RepasJournalier.Statut.PREPARE,
            RepasJournalier.Statut.DISTRIBUTION_OUVERTE,
        }:
            yield Anomalie(
                code="REP_DISTRIBUTION_NON_CLOTUREE",
                cle=f"REP_DISTRIBUTION_NON_CLOTUREE:{repas.id}",
                titre="Distribution de repas non clôturée",
                description="Plus de trois heures après le repas prévu, la distribution reste ouverte ou non clôturée.",
                categorie=AlerteIncident.Categorie.REPAS,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=repas.session_id,
                centre_id=repas.centre_id,
                module_source="repas",
                modele_source="RepasJournalier",
                objet_source_id=repas.id,
                est_bloquante=True,
            )

        if repas.statut_controle_sante == RepasJournalier.StatutControleSante.A_REVOIR and (
            heure <= maintenant + timedelta(hours=6)
        ):
            yield Anomalie(
                code="REP_CONTROLE_SANTE_A_REVOIR",
                cle=f"REP_CONTROLE_SANTE_A_REVOIR:{repas.id}",
                titre="Besoins alimentaires médicaux à revoir",
                description=(
                    "Le repas approche ou est déjà passé alors que les besoins alimentaires opérationnels "
                    "ne sont plus à jour. Aucun détail médical n'est exposé."
                ),
                categorie=AlerteIncident.Categorie.REPAS,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=repas.session_id,
                centre_id=repas.centre_id,
                module_source="repas",
                modele_source="RepasJournalier",
                objet_source_id=repas.id,
                est_bloquante=True,
            )

        if repas.statut in {
            RepasJournalier.Statut.PREPARE,
            RepasJournalier.Statut.DISTRIBUTION_OUVERTE,
            RepasJournalier.Statut.CLOTURE,
        } and repas.nombre_standard_prepare < repas.nombre_standard_prevu:
            yield Anomalie(
                code="REP_PORTIONS_PREPAREES_INSUFFISANTES",
                cle=f"REP_PORTIONS_PREPAREES_INSUFFISANTES:{repas.id}",
                titre="Portions préparées insuffisantes",
                description=(
                    f"Le repas prévoit {repas.nombre_standard_prevu} portions standard mais seulement "
                    f"{repas.nombre_standard_prepare} sont déclarées préparées."
                ),
                categorie=AlerteIncident.Categorie.REPAS,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=repas.session_id,
                centre_id=repas.centre_id,
                module_source="repas",
                modele_source="RepasJournalier",
                objet_source_id=repas.id,
                est_bloquante=True,
            )

        if repas.statut in {
            RepasJournalier.Statut.DISTRIBUTION_OUVERTE,
            RepasJournalier.Statut.CLOTURE,
        } and not SuiviRepas.objects.filter(
            repas_journalier_id=repas.id,
            deleted_at__isnull=True,
        ).exists():
            yield Anomalie(
                code="REP_SUIVIS_ABSENTS",
                cle=f"REP_SUIVIS_ABSENTS:{repas.id}",
                titre="Distribution sans suivi de repas",
                description="La distribution est ouverte ou clôturée mais aucun comptage ni suivi individuel n'existe.",
                categorie=AlerteIncident.Categorie.REPAS,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=repas.session_id,
                centre_id=repas.centre_id,
                module_source="repas",
                modele_source="RepasJournalier",
                objet_source_id=repas.id,
                est_bloquante=True,
            )

    suivis = SuiviRepas.objects.filter(
        type_suivi=SuiviRepas.TypeSuivi.MEDICAL,
        statut_service__in=[
            SuiviRepas.StatutService.SERVI_NON_CONFORME,
            SuiviRepas.StatutService.NON_SERVI,
        ],
        deleted_at__isnull=True,
    ).select_related("repas_journalier__demande_ravitaillement", "affectation_centre")[:limite]
    for suivi in suivis:
        repas = suivi.repas_journalier
        yield Anomalie(
            code="REP_REPAS_MEDICAL_NON_CONFORME",
            cle=f"REP_REPAS_MEDICAL_NON_CONFORME:{suivi.id}",
            titre="Repas adapté non conforme ou non servi",
            description=(
                "Un suivi alimentaire opérationnel indique qu'un repas adapté n'a pas été servi "
                "conformément à la consigne. Les détails médicaux restent dans le module santé."
            ),
            categorie=AlerteIncident.Categorie.REPAS,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=repas.session_id,
            centre_id=repas.centre_id,
            affectation_centre_id=suivi.affectation_centre_id,
            module_source="repas",
            modele_source="SuiviRepas",
            objet_source_id=suivi.id,
            est_bloquante=True,
        )
