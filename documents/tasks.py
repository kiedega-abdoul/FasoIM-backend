from __future__ import annotations

import json
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from accounts.models import Acteur
from accounts.access_context import (
    definir_affectation_courante_id,
    restaurer_affectation_courante_id,
)
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
    WorkflowAutomatiqueAttestationService,
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
def calculer_resultats_centre_task(
    self,
    *,
    session_id,
    centre_id,
    acteur_id,
    affectation_acteur_id=None,
):
    task_id = self.request.id
    _progression(
        task_id,
        statut="EN_COURS",
        progression=5,
        session_id=session_id,
        centre_id=centre_id,
        acteur_id=acteur_id,
        affectation_acteur_id=affectation_acteur_id,
    )

    token = definir_affectation_courante_id(
        affectation_acteur_id
    )

    try:
        acteur = Acteur.objects.get(
            id=acteur_id,
            deleted_at__isnull=True,
        )

        resultat = EligibiliteAttestationService.calculer_centre(
            session_id=session_id,
            centre_id=centre_id,
            acteur=acteur,
        )

        _progression(
            task_id,
            statut="TERMINE",
            progression=100,
            resultat=resultat,
        )
        return _json_safe(resultat)

    except Exception as exc:
        _progression(
            task_id,
            statut="ECHEC",
            progression=100,
            erreur=str(exc),
        )
        raise

    finally:
        restaurer_affectation_courante_id(token)


@shared_task(bind=True, name="documents.generer_attestations_centre")
def generer_attestations_centre_task(
    self,
    *,
    session_id,
    centre_id,
    acteur_id,
    affectation_acteur_id=None,
):
    task_id = self.request.id

    _progression(
        task_id,
        statut="EN_COURS",
        progression=5,
        session_id=session_id,
        centre_id=centre_id,
        acteur_id=acteur_id,
        affectation_acteur_id=affectation_acteur_id,
    )

    token = definir_affectation_courante_id(
        affectation_acteur_id
    )

    try:
        acteur = Acteur.objects.get(
            id=acteur_id,
            deleted_at__isnull=True,
        )

        def publier_progression(*, traites, total, crees, deja):
            if total <= 0:
                pourcentage = 95
            else:
                # La génération occupe la plage de 5 % à 95 %.
                pourcentage = 5 + int(
                    (traites / total) * 90
                )
                pourcentage = min(95, max(5, pourcentage))

            _progression(
                task_id,
                statut="EN_COURS",
                progression=pourcentage,
                session_id=session_id,
                centre_id=centre_id,
                acteur_id=acteur_id,
                affectation_acteur_id=affectation_acteur_id,
                traites=traites,
                total=total,
                generes=crees,
                deja_generes=deja,
                message=(
                    f"Attestations préparées : "
                    f"{traites}/{total}"
                ),
            )

        resultat = AttestationService.generer_centre(
            session_id=session_id,
            centre_id=centre_id,
            acteur=acteur,
            progression_callback=publier_progression,
        )

        _progression(
            task_id,
            statut="TERMINE",
            progression=100,
            resultat=resultat,
        )
        return _json_safe(resultat)

    except Exception as exc:
        _progression(
            task_id,
            statut="ECHEC",
            progression=100,
            erreur=str(exc),
        )
        raise

    finally:
        restaurer_affectation_courante_id(token)


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
    """Prépare automatiquement les attestations des centres réellement finalisés."""
    aujourd_hui = timezone.localdate()
    sessions = list(
        SessionImmersion.objects.select_related("parametres").filter(
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
    )
    prets = 0
    bloques = 0
    erreurs = []
    for session in sessions:
        for centre in PublicationService._centres_attendus(session):
            try:
                resultat = WorkflowAutomatiqueAttestationService.preparer_centre(
                    session=session, centre=centre
                )
                if resultat.get("prepare"):
                    prets += 1
                else:
                    bloques += 1
            except Exception as exc:
                bloques += 1
                erreurs.append({"session_id": session.id, "centre_id": centre.id, "motif": str(exc)})

        etat = SessionClotureService.verifier(session)
        session.cloture_proposee_blocages = etat.en_dict().get("blocages", [])
        session.cloture_proposee_at = timezone.now() if etat.cloturable else None
        session.save(update_fields=[
            "cloture_proposee_blocages", "cloture_proposee_at", "updated_at"
        ])
        if etat.cloturable:
            NotificationService.planifier_acteurs_role(
                code_role="ADMINISTRATEUR",
                sujet="Session prête à clôturer",
                message=(
                    f"La session {session.nom} a été vérifiée automatiquement et peut être clôturée."
                ),
                type_message=getattr(TypesMessage, "SESSION_PRETE_CLOTURE", "SESSION_PRETE_CLOTURE"),
                cle_evenement=f"SESSION_PRETE_CLOTURE:{session.id}",
                session_id=session.id,
                contexte={"session_id": session.id},
            )
    return {
        "sessions": len(sessions),
        "centres_prets": prets,
        "centres_bloques": bloques,
        "erreurs": erreurs,
    }


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
