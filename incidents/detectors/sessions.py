from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from sessions_app.models import ParametreSession, SessionImmersion

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "SES_PARAMETRES_ABSENTS",
    "SES_PARAMETRES_SUPPRIMES",
    "SES_STATUT_DATE_INCOHERENT",
    "SES_PREPARATION_TROP_TARDIVE",
    "SES_MODULES_SANS_DIRECTIVES",
)


def _taille_lot():
    return int(getattr(settings, "INCIDENTS_TAILLE_LOT_SCAN", getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500)))


def detecter():
    aujourd_hui = timezone.localdate()
    operationnelles = SessionImmersion.objects.filter(
        statut__in=[
            SessionImmersion.Statut.OUVERTE,
            SessionImmersion.Statut.EN_PREPARATION,
            SessionImmersion.Statut.EN_COURS,
        ],
        deleted_at__isnull=True,
    ).select_related("parametres").iterator(chunk_size=_taille_lot())

    for session in operationnelles:
        try:
            parametres = session.parametres
        except ParametreSession.DoesNotExist:
            parametres = None
        if not parametres:
            yield Anomalie(
                code="SES_PARAMETRES_ABSENTS",
                cle=f"SES_PARAMETRES_ABSENTS:{session.id}",
                titre="Session opérationnelle sans paramètres",
                description="La session est ouverte, en préparation ou en cours sans bloc de paramètres actif.",
                categorie=AlerteIncident.Categorie.SESSION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.SESSION,
                session_id=session.id,
                module_source="sessions_app",
                modele_source="SessionImmersion",
                objet_source_id=session.id,
                est_bloquante=True,
            )
            continue
        if parametres.deleted_at is not None:
            yield Anomalie(
                code="SES_PARAMETRES_SUPPRIMES",
                cle=f"SES_PARAMETRES_SUPPRIMES:{session.id}",
                titre="Paramètres de session supprimés",
                description="La session opérationnelle référence des paramètres supprimés logiquement.",
                categorie=AlerteIncident.Categorie.SESSION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.SESSION,
                session_id=session.id,
                module_source="sessions_app",
                modele_source="ParametreSession",
                objet_source_id=parametres.id,
                est_bloquante=True,
            )

        if session.statut == SessionImmersion.Statut.EN_COURS and not (
            session.date_debut <= aujourd_hui <= session.date_fin
        ):
            yield Anomalie(
                code="SES_STATUT_DATE_INCOHERENT",
                cle=f"SES_STATUT_DATE_INCOHERENT:{session.id}:EN_COURS",
                titre="Session en cours hors de sa période",
                description="Le statut EN_COURS ne correspond pas aux dates configurées pour la session.",
                categorie=AlerteIncident.Categorie.SESSION,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.SESSION,
                session_id=session.id,
                module_source="sessions_app",
                modele_source="SessionImmersion",
                objet_source_id=session.id,
            )

        if (
            session.statut == SessionImmersion.Statut.EN_PREPARATION
            and session.date_debut < aujourd_hui
        ):
            yield Anomalie(
                code="SES_PREPARATION_TROP_TARDIVE",
                cle=f"SES_PREPARATION_TROP_TARDIVE:{session.id}",
                titre="Session encore en préparation après sa date de début",
                description="La date de début est dépassée mais la session n'est pas passée en cours.",
                categorie=AlerteIncident.Categorie.SESSION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.SESSION,
                session_id=session.id,
                module_source="sessions_app",
                modele_source="SessionImmersion",
                objet_source_id=session.id,
                est_bloquante=True,
            )

        if (
            session.date_debut <= aujourd_hui + timedelta(days=2)
            and not (parametres.directives_generales or parametres.consignes_generales)
        ):
            yield Anomalie(
                code="SES_MODULES_SANS_DIRECTIVES",
                cle=f"SES_MODULES_SANS_DIRECTIVES:{session.id}",
                titre="Session proche sans directives générales",
                description="La session débute bientôt mais aucune directive ni consigne générale n'est renseignée.",
                categorie=AlerteIncident.Categorie.SESSION,
                gravite=AlerteIncident.NiveauGravite.MOYEN,
                type_concerne=AlerteIncident.TypeConcerne.SESSION,
                session_id=session.id,
                module_source="sessions_app",
                modele_source="ParametreSession",
                objet_source_id=parametres.id,
            )

    terminees_non_terminees = SessionImmersion.objects.filter(
        date_fin__lt=aujourd_hui,
        statut__in=[
            SessionImmersion.Statut.OUVERTE,
            SessionImmersion.Statut.EN_PREPARATION,
            SessionImmersion.Statut.EN_COURS,
        ],
        deleted_at__isnull=True,
    ).iterator(chunk_size=_taille_lot())
    for session in terminees_non_terminees:
        yield Anomalie(
            code="SES_STATUT_DATE_INCOHERENT",
            cle=f"SES_STATUT_DATE_INCOHERENT:{session.id}:DATE_FIN",
            titre="Session non terminée après sa date de fin",
            description="La date de fin est dépassée mais le statut de la session reste opérationnel.",
            categorie=AlerteIncident.Categorie.SESSION,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.SESSION,
            session_id=session.id,
            module_source="sessions_app",
            modele_source="SessionImmersion",
            objet_source_id=session.id,
        )
