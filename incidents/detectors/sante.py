from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from affectations.models import AffectationCentre
from sante.models import RestrictionMedicale, VisiteMedicale
from sessions_app.models import SessionImmersion

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "SAN_VISITE_OBLIGATOIRE_ABSENTE",
    "SAN_VISITE_COURANTE_MULTIPLE",
    "SAN_RESULTAT_A_APPLIQUER_EN_RETARD",
    "SAN_APPLICATION_RESULTAT_ECHEC",
    "SAN_RESTRICTION_EXPIREE_ACTIVE",
    "SAN_RESTRICTION_SANS_CONSIGNE",
    "SAN_VISITE_PERIMETRE_INCOHERENT",
)


def _limite():
    return int(getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500))


def detecter():
    maintenant = timezone.now()
    aujourd_hui = timezone.localdate()
    limite = _limite()

    affectations = AffectationCentre.objects.filter(
        statut=AffectationCentre.Statut.ACTIVE,
        deleted_at__isnull=True,
        session__statut=SessionImmersion.Statut.EN_COURS,
        session__deleted_at__isnull=True,
        session__parametres__visite_medicale_active=True,
        session__parametres__deleted_at__isnull=True,
    ).select_related("session", "centre")[:limite]
    for affectation in affectations:
        existe = VisiteMedicale.objects.filter(
            affectation_centre_id=affectation.id,
            est_courante=True,
            statut__in=[VisiteMedicale.Statut.BROUILLON, VisiteMedicale.Statut.VALIDEE],
            deleted_at__isnull=True,
        ).exists()
        if not existe:
            yield Anomalie(
                code="SAN_VISITE_OBLIGATOIRE_ABSENTE",
                cle=f"SAN_VISITE_OBLIGATOIRE_ABSENTE:{affectation.id}",
                titre="Visite médicale obligatoire absente",
                description=(
                    "La session est en cours et la visite médicale est activée, mais aucune visite "
                    "courante n'est enregistrée pour l'immergé."
                ),
                categorie=AlerteIncident.Categorie.SANTE,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                affectation_centre_id=affectation.id,
                module_source="sante",
                modele_source="VisiteMedicale",
                est_bloquante=True,
            )

    multiples = (
        VisiteMedicale.objects.filter(
            est_courante=True,
            deleted_at__isnull=True,
        )
        .values("affectation_centre_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)[:limite]
    )
    for ligne in multiples:
        ac = AffectationCentre.objects.filter(id=ligne["affectation_centre_id"]).first()
        yield Anomalie(
            code="SAN_VISITE_COURANTE_MULTIPLE",
            cle=f"SAN_VISITE_COURANTE_MULTIPLE:{ligne['affectation_centre_id']}",
            titre="Plusieurs visites médicales courantes",
            description="Plus d'une visite médicale est marquée courante pour la même affectation centre.",
            categorie=AlerteIncident.Categorie.SANTE,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=ac.session_id if ac else None,
            centre_id=ac.centre_id if ac else None,
            affectation_centre_id=ac.id if ac else None,
            module_source="sante",
            modele_source="VisiteMedicale",
            est_bloquante=True,
            contexte={"nombre_visites_courantes": ligne["total"]},
        )

    retard = maintenant - timedelta(minutes=15)
    visites_retard = VisiteMedicale.objects.filter(
        statut=VisiteMedicale.Statut.VALIDEE,
        statut_application__in=[
            VisiteMedicale.StatutApplication.A_APPLIQUER,
            VisiteMedicale.StatutApplication.EN_COURS,
        ],
        updated_at__lt=retard,
        deleted_at__isnull=True,
    ).select_related("affectation_centre")[:limite]
    for visite in visites_retard:
        ac = visite.affectation_centre
        yield Anomalie(
            code="SAN_RESULTAT_A_APPLIQUER_EN_RETARD",
            cle=f"SAN_RESULTAT_A_APPLIQUER_EN_RETARD:{visite.id}",
            titre="Résultat médical non appliqué",
            description=(
                "Une visite validée attend toujours l'application de ses conséquences opérationnelles. "
                "Aucune donnée médicale confidentielle n'est exposée dans cette alerte."
            ),
            categorie=AlerteIncident.Categorie.SANTE,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=visite.session_id,
            centre_id=visite.centre_id,
            affectation_centre_id=ac.id,
            module_source="sante",
            modele_source="VisiteMedicale",
            objet_source_id=visite.id,
            est_bloquante=True,
        )

    for visite in VisiteMedicale.objects.filter(
        statut_application=VisiteMedicale.StatutApplication.ECHEC,
        deleted_at__isnull=True,
    ).select_related("affectation_centre")[:limite]:
        yield Anomalie(
            code="SAN_APPLICATION_RESULTAT_ECHEC",
            cle=f"SAN_APPLICATION_RESULTAT_ECHEC:{visite.id}",
            titre="Échec d'application d'un résultat médical",
            description=(
                "Les conséquences opérationnelles d'une visite médicale n'ont pas pu être appliquées. "
                "Le détail technique est conservé dans le module santé."
            ),
            categorie=AlerteIncident.Categorie.SANTE,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=visite.session_id,
            centre_id=visite.centre_id,
            affectation_centre_id=visite.affectation_centre_id,
            module_source="sante",
            modele_source="VisiteMedicale",
            objet_source_id=visite.id,
            est_bloquante=True,
        )

    for restriction in RestrictionMedicale.objects.filter(
        statut=RestrictionMedicale.Statut.ACTIVE,
        date_fin__lt=aujourd_hui,
        deleted_at__isnull=True,
    ).select_related("visite_medicale")[:limite]:
        visite = restriction.visite_medicale
        yield Anomalie(
            code="SAN_RESTRICTION_EXPIREE_ACTIVE",
            cle=f"SAN_RESTRICTION_EXPIREE_ACTIVE:{restriction.id}",
            titre="Restriction médicale expirée encore active",
            description="Une restriction a dépassé sa date de fin mais son statut reste actif.",
            categorie=AlerteIncident.Categorie.SANTE,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=visite.session_id,
            centre_id=visite.centre_id,
            affectation_centre_id=visite.affectation_centre_id,
            module_source="sante",
            modele_source="RestrictionMedicale",
            objet_source_id=restriction.id,
        )

    for restriction in RestrictionMedicale.objects.filter(
        statut=RestrictionMedicale.Statut.ACTIVE,
        consigne_operationnelle="",
        deleted_at__isnull=True,
    ).select_related("visite_medicale")[:limite]:
        visite = restriction.visite_medicale
        yield Anomalie(
            code="SAN_RESTRICTION_SANS_CONSIGNE",
            cle=f"SAN_RESTRICTION_SANS_CONSIGNE:{restriction.id}",
            titre="Restriction active sans consigne opérationnelle",
            description=(
                "Une restriction active ne contient aucune consigne exploitable par les modules concernés. "
                "Le détail médical reste confidentiel."
            ),
            categorie=AlerteIncident.Categorie.SANTE,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=visite.session_id,
            centre_id=visite.centre_id,
            affectation_centre_id=visite.affectation_centre_id,
            module_source="sante",
            modele_source="RestrictionMedicale",
            objet_source_id=restriction.id,
            est_bloquante=True,
        )

    visites = VisiteMedicale.objects.filter(deleted_at__isnull=True).select_related(
        "affectation_centre"
    )[:limite]
    for visite in visites:
        ac = visite.affectation_centre
        if visite.session_id != ac.session_id or visite.centre_id != ac.centre_id:
            yield Anomalie(
                code="SAN_VISITE_PERIMETRE_INCOHERENT",
                cle=f"SAN_VISITE_PERIMETRE_INCOHERENT:{visite.id}",
                titre="Périmètre d'une visite médicale incohérent",
                description="La session ou le centre de la visite ne correspond pas à l'affectation centre.",
                categorie=AlerteIncident.Categorie.SANTE,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=ac.session_id,
                centre_id=ac.centre_id,
                affectation_centre_id=ac.id,
                module_source="sante",
                modele_source="VisiteMedicale",
                objet_source_id=visite.id,
                est_bloquante=True,
            )
