import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.template.defaultfilters import linebreaksbr
from django.utils.html import strip_tags

from .models import Acteur
from .repository import AffectationActeurRepository, ControleAccesRepository

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def envoyer_email_bienvenue_acteur_task(self, acteur_id, mot_de_passe_temporaire):
    """Envoie l'email de bienvenue d'un acteur via Celery/Redis."""
    acteur = Acteur.objects.filter(id=acteur_id, deleted_at__isnull=True).first()
    if not acteur or not acteur.email:
        return {"envoye": False, "motif": "acteur_introuvable_ou_email_absent"}

    login_url = getattr(settings, "FASOIM_LOGIN_URL", None) or getattr(
        settings,
        "FRONTEND_URL",
        "http://127.0.0.1:8000/admin/",
    )
    nom = acteur.nom_complet or acteur.username
    sujet = "Bienvenue sur FasoIM"
    message = f"""Bonjour {nom},

Votre compte FasoIM a été créé.

Informations de connexion :
- Nom d'utilisateur : {acteur.username}
- Email : {acteur.email}
- Mot de passe temporaire : {mot_de_passe_temporaire}

Connectez-vous à FasoIM ici : {login_url}

Après votre première connexion, modifiez votre mot de passe dans votre profil.

Cordialement,
L'équipe FasoIM
"""

    try:
        send_mail(
            subject=sujet,
            message=strip_tags(linebreaksbr(message)),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[acteur.email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.exception("Erreur lors de l'envoi de l'email de bienvenue à l'acteur %s", acteur_id)
        raise self.retry(exc=exc)

    return {"envoye": True, "acteur_id": acteur_id}


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
