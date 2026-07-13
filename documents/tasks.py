from __future__ import annotations

import json
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from accounts.models import Acteur
from affectations.models import CentreImmersion
from audit.models import JournalAction
from audit.service import JournalActionService
from notifications.service import NotificationService, TypesMessage
from sessions_app.models import SessionImmersion

from .models import PublicationOfficielle
from .service import (
    AttestationService,
    CentreCertificationService,
    EligibiliteAttestationService,
    PublicationService,
    RapportService,
    SessionClotureService,
)

logger = logging.getLogger(__name__)

PROGRESSION_TTL = int(getattr(settings, "DOCUMENTS_PROGRESS_TTL_SECONDS", 24 * 3600))


def cle_progression(task_id):
    return f"documents:progression:{task_id}"


def _json_safe(valeur):
    return json.loads(json.dumps(valeur, default=str))


def _progression(task_id, **donnees):
    actuel = cache.get(cle_progression(task_id)) or {}
    actuel.update(donnees)
    cache.set(cle_progression(task_id), _json_safe(actuel), PROGRESSION_TTL)
    return actuel


@shared_task(bind=True, name="documents.calculer_resultats_centre")
def calculer_resultats_centre_task(self, *, session_id, centre_id, acteur_id):
    task_id = self.request.id
    _progression(task_id, statut="EN_COURS", progression=5, session_id=session_id, centre_id=centre_id, acteur_id=acteur_id)
    acteur = Acteur.objects.get(id=acteur_id, deleted_at__isnull=True)
    try:
        resultat = EligibiliteAttestationService.calculer_centre(
            session_id=session_id,
            centre_id=centre_id,
            acteur=acteur,
        )
        _progression(task_id, statut="TERMINE", progression=100, resultat=resultat)
        return _json_safe(resultat)
    except Exception as exc:
        _progression(task_id, statut="ECHEC", progression=100, erreur=str(exc))
        raise


@shared_task(bind=True, name="documents.generer_attestations_centre")
def generer_attestations_centre_task(self, *, session_id, centre_id, acteur_id):
    task_id = self.request.id
    _progression(task_id, statut="EN_COURS", progression=5, session_id=session_id, centre_id=centre_id, acteur_id=acteur_id)
    acteur = Acteur.objects.get(id=acteur_id, deleted_at__isnull=True)
    try:
        resultat = AttestationService.generer_centre(
            session_id=session_id,
            centre_id=centre_id,
            acteur=acteur,
        )
        _progression(task_id, statut="TERMINE", progression=100, resultat=resultat)
        return _json_safe(resultat)
    except Exception as exc:
        _progression(task_id, statut="ECHEC", progression=100, erreur=str(exc))
        raise


@shared_task(bind=True, name="documents.generer_rapport")
def generer_rapport_task(
    self,
    *,
    type_document,
    format_fichier,
    session_id,
    acteur_id,
    region_id=None,
    centre_id=None,
    parametres=None,
):
    task_id = self.request.id
    _progression(
        task_id,
        statut="EN_COURS",
        progression=5,
        session_id=session_id,
        region_id=region_id,
        centre_id=centre_id,
        acteur_id=acteur_id,
    )
    acteur = Acteur.objects.get(id=acteur_id, deleted_at__isnull=True)
    try:
        document = RapportService.generer(
            type_document=type_document,
            format_fichier=format_fichier,
            session_id=session_id,
            acteur=acteur,
            region_id=region_id,
            centre_id=centre_id,
            parametres=parametres or {},
        )
        resultat = {
            "document_id": document.id,
            "numero_document": document.numero_document,
            "statut": document.statut,
        }
        _progression(task_id, statut="TERMINE", progression=100, resultat=resultat)
        return resultat
    except Exception as exc:
        _progression(task_id, statut="ECHEC", progression=100, erreur=str(exc))
        raise


@shared_task(bind=True, name="documents.detecter_centres_prets_attestations")
def detecter_centres_prets_attestations_task(self):
    """Avertit une seule fois les responsables lorsque leur centre est prêt.

    La date de fin déclenche seulement le contrôle. Elle ne clôture jamais la
    session et ne génère aucune attestation à la place du Responsable.
    """
    aujourd_hui = timezone.localdate()
    sessions = SessionImmersion.objects.select_related("parametres").filter(
        date_fin__lte=aujourd_hui,
        parametres__attestation_active=True,
        deleted_at__isnull=True,
    ).exclude(
        statut__in=[
            SessionImmersion.Statut.TERMINEE,
            SessionImmersion.Statut.ARCHIVEE,
            SessionImmersion.Statut.ANNULEE,
        ]
    )
    sessions = list(sessions)
    prets = 0
    bloques = 0
    for session in sessions:
        centres = PublicationService._centres_attendus(session)
        for centre in centres:
            etat = CentreCertificationService.verifier(session=session, centre=centre)
            if not etat["pret"]:
                bloques += 1
                continue
            prets += 1
            NotificationService.planifier_acteurs_role(
                code_role="RESPONSABLE_CENTRE",
                sujet="Attestations à préparer pour votre centre",
                message=(
                    f"La session {session.nom} a atteint sa date de fin et les opérations "
                    f"du centre {centre.nom} sont finalisées. Vous pouvez maintenant lancer "
                    "le calcul des résultats finaux et préparer les attestations."
                ),
                type_message=getattr(TypesMessage, "CENTRE_PRET_ATTESTATIONS", "CENTRE_PRET_ATTESTATIONS"),
                cle_evenement=f"CENTRE_PRET_ATTESTATIONS:{session.id}:{centre.id}",
                session_id=session.id,
                region_code=centre.region.code,
                centre_id=centre.id,
                contexte={"session_id": session.id, "centre_id": centre.id},
            )
    return {"sessions": len(sessions), "centres_prets": prets, "centres_bloques": bloques}


@shared_task(bind=True, name="documents.signer_attestations_region")
def signer_attestations_region_task(self, *, publication_id, acteur_id):
    task_id = self.request.id
    publication = PublicationOfficielle.objects.select_related("session", "region", "centre").get(
        id=publication_id, deleted_at__isnull=True
    )
    _progression(
        task_id,
        statut="EN_COURS",
        progression=5,
        session_id=publication.session_id,
        region_id=publication.region_id,
        centre_id=publication.centre_id,
        acteur_id=acteur_id,
    )
    acteur = Acteur.objects.get(id=acteur_id, deleted_at__isnull=True)
    try:
        resultat = AttestationService.signer_region(
            publication_id=publication_id,
            acteur=acteur,
        )
        _progression(task_id, statut="TERMINE", progression=100, resultat=resultat)
        return _json_safe(resultat)
    except Exception as exc:
        _progression(task_id, statut="ECHEC", progression=100, erreur=str(exc))
        raise


@shared_task(bind=True, name="documents.publier_session")
def publier_session_task(self, *, session_id, type_publication, acteur_id):
    task_id = self.request.id
    _progression(
        task_id,
        statut="EN_COURS",
        progression=5,
        session_id=session_id,
        acteur_id=acteur_id,
        type_publication=type_publication,
    )
    acteur = Acteur.objects.get(id=acteur_id, deleted_at__isnull=True)
    try:
        publication = PublicationService.publier_session(
            session_id=session_id,
            type_publication=type_publication,
            acteur=acteur,
        )
        resultat = {
            "publication_id": publication.id,
            "reference": publication.reference,
            "statut": publication.statut,
        }
        _progression(task_id, statut="TERMINE", progression=100, resultat=resultat)
        return resultat
    except Exception as exc:
        _progression(task_id, statut="ECHEC", progression=100, erreur=str(exc))
        raise


@shared_task(bind=True, name="documents.verifier_integrite_et_cloture")
def verifier_integrite_et_cloture_task(self, *, session_id):
    session = SessionImmersion.objects.select_related("parametres").get(id=session_id, deleted_at__isnull=True)
    etat = SessionClotureService.verifier(session)
    return _json_safe(etat.en_dict())
