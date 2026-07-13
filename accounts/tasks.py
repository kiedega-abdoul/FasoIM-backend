import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from .models import Acteur
from .repository import AffectationActeurRepository, ControleAccesRepository

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def envoyer_email_bienvenue_acteur_task(self, acteur_id, mot_de_passe_temporaire):
    """Compatibilité accounts : délègue l'envoi au module notifications."""
    acteur = Acteur.objects.filter(id=acteur_id, deleted_at__isnull=True).first()
    if not acteur or not acteur.email:
        return {"envoye": False, "motif": "acteur_introuvable_ou_email_absent"}

    from notifications.service import ErreurEnvoiEmail, NotificationService, TypesMessage

    sujet, message = NotificationService.message_bienvenue_acteur(
        acteur,
        mot_de_passe_temporaire,
    )
    try:
        resultat = NotificationService.envoyer_email(
            destinataire=acteur.email,
            sujet=sujet,
            message=message,
            type_message=TypesMessage.BIENVENUE_ACTEUR,
            cle_evenement=f"BIENVENUE_ACTEUR:{acteur.id}:{acteur.created_at.isoformat()}",
            acteur=acteur,
            objet=acteur,
            contexte={"mode_contact": "DIRECT"},
            task_id=self.request.id,
            tentative=int(getattr(self.request, "retries", 0)) + 1,
        )
        return resultat.as_dict()
    except ErreurEnvoiEmail as exc:
        logger.exception("Erreur lors de l'envoi de l'email de bienvenue à l'acteur %s", acteur_id)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def supprimer_acteur_logiquement_en_cascade_task(self, acteur_id, auteur_id=None):
    """Supprime logiquement un acteur et ses enfants métier accounts."""
    try:
        from .service import ActeurService

        acteur = ActeurService.supprimer_logiquement_synchrone(acteur_id, auteur=auteur_id)
        return {"supprime": bool(acteur), "acteur_id": acteur_id}
    except Exception as exc:
        logger.exception("Erreur suppression logique acteur %s", acteur_id)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def recalculer_cache_permissions_acteur_task(self, acteur_id):
    """Recalcule le cache Redis des permissions effectives d'un acteur."""
    try:
        affectations = AffectationActeurRepository.lister_actives_par_acteur(acteur_id)
        total_affectations = 0

        for affectation in affectations:
            codes = sorted(ControleAccesRepository.get_permission_codes_acteur(acteur_id, affectation))
            cache.set(
                f"accounts:permissions:{acteur_id}:{affectation.id}",
                codes,
                timeout=60 * 30,
            )
            total_affectations += 1

        cache.set(
            f"accounts:permissions:{acteur_id}:affectations_actives",
            total_affectations,
            timeout=60 * 30,
        )
        return {"acteur_id": acteur_id, "affectations": total_affectations}
    except Exception as exc:
        logger.exception("Erreur recalcul cache permissions acteur %s", acteur_id)
        raise self.retry(exc=exc)
