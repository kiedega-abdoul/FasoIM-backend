from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Exists, F, OuterRef
from django.utils import timezone

from affectations.models import AffectationCentre, AffectationRegionale, CentreImmersion, RegionImmersion
from sessions_app.models import SessionImmersion

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "AFF_REGION_ACTIVE_SANS_CENTRE",
    "AFF_CENTRE_SANS_REGION_ACTIVE",
    "AFF_CENTRE_REGION_INCOHERENTE",
    "AFF_CENTRE_HORS_SERVICE_UTILISE",
    "AFF_CENTRE_SURCAPACITE",
    "AFF_PROPOSITION_EN_RETARD",
    "AFF_REGION_DESACTIVEE_UTILISEE",
)


def _taille_lot():
    return int(getattr(settings, "INCIDENTS_TAILLE_LOT_SCAN", getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500)))


def detecter():
    maintenant = timezone.now()
    taille_lot = _taille_lot()

    centre_actif = AffectationCentre.objects.filter(
        affectation_regionale_id=OuterRef("pk"),
        statut=AffectationCentre.Statut.ACTIVE,
        deleted_at__isnull=True,
    )
    regionales = (
        AffectationRegionale.objects.filter(
            statut=AffectationRegionale.Statut.ACTIVE,
            deleted_at__isnull=True,
            session__statut__in=[
                SessionImmersion.Statut.EN_PREPARATION,
                SessionImmersion.Statut.EN_COURS,
            ],
            session__deleted_at__isnull=True,
        )
        .annotate(possede_centre_actif=Exists(centre_actif))
        .select_related("immerge", "session", "region")
        .iterator(chunk_size=taille_lot)
    )
    for regionale in regionales:
        centre_exige = regionale.session.statut == SessionImmersion.Statut.EN_COURS or (
            regionale.session.date_debut <= timezone.localdate() + timedelta(days=3)
        )
        if centre_exige and not regionale.possede_centre_actif:
            yield Anomalie(
                code="AFF_REGION_ACTIVE_SANS_CENTRE",
                cle=f"AFF_REGION_ACTIVE_SANS_CENTRE:{regionale.id}",
                titre="Affectation régionale sans centre",
                description="Une affectation régionale active n'est suivie d'aucune affectation centre active.",
                categorie=AlerteIncident.Categorie.AFFECTATION,
                gravite=(
                    AlerteIncident.NiveauGravite.CRITIQUE
                    if regionale.session.statut == SessionImmersion.Statut.EN_COURS
                    else AlerteIncident.NiveauGravite.ELEVE
                ),
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=regionale.session_id,
                module_source="affectations",
                modele_source="AffectationRegionale",
                objet_source_id=regionale.id,
                est_bloquante=regionale.session.statut == SessionImmersion.Statut.EN_COURS,
            )

    centres = AffectationCentre.objects.filter(
        statut=AffectationCentre.Statut.ACTIVE,
        deleted_at__isnull=True,
    ).select_related("immerge", "session", "centre__region", "affectation_regionale").iterator(chunk_size=taille_lot)
    for affectation in centres:
        regionale = affectation.affectation_regionale
        if not regionale.est_active:
            yield Anomalie(
                code="AFF_CENTRE_SANS_REGION_ACTIVE",
                cle=f"AFF_CENTRE_SANS_REGION_ACTIVE:{affectation.id}",
                titre="Affectation centre sans région active",
                description="Une affectation centre active dépend d'une affectation régionale inactive ou supprimée.",
                categorie=AlerteIncident.Categorie.AFFECTATION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                affectation_centre_id=affectation.id,
                module_source="affectations",
                modele_source="AffectationCentre",
                objet_source_id=affectation.id,
                est_bloquante=True,
            )
        if (
            affectation.session_id != regionale.session_id
            or affectation.immerge_id != regionale.immerge_id
            or affectation.centre.region_id != regionale.region_id
        ):
            yield Anomalie(
                code="AFF_CENTRE_REGION_INCOHERENTE",
                cle=f"AFF_CENTRE_REGION_INCOHERENTE:{affectation.id}",
                titre="Affectation centre incohérente",
                description="La session, l'immergé ou la région du centre ne correspond pas à l'affectation régionale.",
                categorie=AlerteIncident.Categorie.AFFECTATION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                affectation_centre_id=affectation.id,
                module_source="affectations",
                modele_source="AffectationCentre",
                objet_source_id=affectation.id,
                est_bloquante=True,
            )
        if affectation.centre.statut != CentreImmersion.Statut.ACTIF or affectation.centre.deleted_at:
            yield Anomalie(
                code="AFF_CENTRE_HORS_SERVICE_UTILISE",
                cle=f"AFF_CENTRE_HORS_SERVICE_UTILISE:{affectation.id}",
                titre="Immergé affecté à un centre hors service",
                description="Une affectation active utilise un centre en maintenance, désactivé, archivé ou supprimé.",
                categorie=AlerteIncident.Categorie.AFFECTATION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                affectation_centre_id=affectation.id,
                module_source="affectations",
                modele_source="AffectationCentre",
                objet_source_id=affectation.id,
                est_bloquante=True,
            )

    occupations = (
        AffectationCentre.objects.filter(
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        )
        .values("session_id", "centre_id", "centre__nom", "centre__capacite_totale")
        .annotate(effectif=Count("id"))
        .filter(effectif__gt=F("centre__capacite_totale")).iterator(chunk_size=taille_lot)
    )
    for ligne in occupations:
        yield Anomalie(
            code="AFF_CENTRE_SURCAPACITE",
            cle=f"AFF_CENTRE_SURCAPACITE:{ligne['session_id']}:{ligne['centre_id']}",
            titre=f"Centre en surcapacité : {ligne['centre__nom']}",
            description=(
                f"Le centre compte {ligne['effectif']} affectations actives pour une capacité de "
                f"{ligne['centre__capacite_totale']}."
            ),
            categorie=AlerteIncident.Categorie.AFFECTATION,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.CENTRE,
            session_id=ligne["session_id"],
            centre_id=ligne["centre_id"],
            module_source="affectations",
            modele_source="CentreImmersion",
            objet_source_id=ligne["centre_id"],
            est_bloquante=True,
            contexte={"effectif": ligne["effectif"], "capacite": ligne["centre__capacite_totale"]},
        )

    seuil = maintenant - timedelta(hours=24)
    propositions = list(
        AffectationRegionale.objects.filter(
            statut=AffectationRegionale.Statut.PROPOSEE,
            date_affectation__lt=seuil,
            deleted_at__isnull=True,
        ).values("id", "session_id").iterator(chunk_size=taille_lot)
    ) + list(
        AffectationCentre.objects.filter(
            statut=AffectationCentre.Statut.PROPOSEE,
            date_affectation__lt=seuil,
            deleted_at__isnull=True,
        ).values("id", "session_id", "centre_id").iterator(chunk_size=taille_lot)
    )
    for ligne in propositions:
        modele = "AffectationCentre" if ligne.get("centre_id") else "AffectationRegionale"
        yield Anomalie(
            code="AFF_PROPOSITION_EN_RETARD",
            cle=f"AFF_PROPOSITION_EN_RETARD:{modele}:{ligne['id']}",
            titre="Proposition d'affectation non traitée",
            description="Une proposition d'affectation attend une décision depuis plus de vingt-quatre heures.",
            categorie=AlerteIncident.Categorie.AFFECTATION,
            gravite=AlerteIncident.NiveauGravite.MOYEN,
            type_concerne=AlerteIncident.TypeConcerne.DONNEE,
            session_id=ligne["session_id"],
            centre_id=ligne.get("centre_id"),
            module_source="affectations",
            modele_source=modele,
            objet_source_id=ligne["id"],
        )

    for affectation in AffectationRegionale.objects.filter(
        statut=AffectationRegionale.Statut.ACTIVE,
        deleted_at__isnull=True,
        region__statut=RegionImmersion.Statut.DESACTIVEE,
    ).select_related("region").iterator(chunk_size=taille_lot):
        yield Anomalie(
            code="AFF_REGION_DESACTIVEE_UTILISEE",
            cle=f"AFF_REGION_DESACTIVEE_UTILISEE:{affectation.id}",
            titre="Affectation active dans une région désactivée",
            description="Une région désactivée possède encore une affectation régionale active.",
            categorie=AlerteIncident.Categorie.AFFECTATION,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=affectation.session_id,
            module_source="affectations",
            modele_source="AffectationRegionale",
            objet_source_id=affectation.id,
            est_bloquante=True,
        )
