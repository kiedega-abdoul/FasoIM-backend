from __future__ import annotations

import time

from celery.signals import task_failure, task_postrun, task_prerun
from django.core.cache import cache

from .models import JournalAction
from .service import JournalActionService


TTL_DEBUT_TACHE = 60 * 60


def _cle(task_id):
    return f"audit:celery:debut:{task_id}"


def _module(nom_tache):
    return str(nom_tache or "celery").split(".", 1)[0][:80]


def _contexte_resultat(resultat):
    if isinstance(resultat, dict):
        return {"resultat_tache": resultat}
    if resultat is None:
        return {}
    return {"resultat_tache": str(resultat)[:1000]}


@task_prerun.connect
def enregistrer_debut_tache(task_id=None, task=None, **kwargs):
    if task_id:
        cache.set(_cle(task_id), time.monotonic(), TTL_DEBUT_TACHE)


@task_postrun.connect
def journaliser_fin_tache(task_id=None, task=None, state=None, retval=None, **kwargs):
    if not task_id or state != "SUCCESS":
        return
    nom = getattr(task, "name", "") or "tache_celery"
    if nom == "audit.generer_export":
        cache.delete(_cle(task_id))
        return
    debut = cache.get(_cle(task_id))
    duree_ms = int((time.monotonic() - debut) * 1000) if debut else None
    cache.delete(_cle(task_id))
    JournalActionService.journaliser_succes(
        code_action=nom,
        module_source=_module(nom),
        origine=JournalAction.Origine.CELERY,
        canal=JournalAction.Canal.CELERY,
        task_id=task_id,
        duree_ms=duree_ms,
        contexte=_contexte_resultat(retval),
    )


@task_failure.connect
def journaliser_echec_tache(task_id=None, sender=None, exception=None, **kwargs):
    if not task_id:
        return
    nom = getattr(sender, "name", "") or "tache_celery"
    if nom == "audit.generer_export":
        cache.delete(_cle(task_id))
        return
    debut = cache.get(_cle(task_id))
    duree_ms = int((time.monotonic() - debut) * 1000) if debut else None
    cache.delete(_cle(task_id))
    JournalActionService.journaliser_echec(
        code_action=nom,
        module_source=_module(nom),
        origine=JournalAction.Origine.CELERY,
        canal=JournalAction.Canal.CELERY,
        task_id=task_id,
        duree_ms=duree_ms,
        motif=str(exception or "Échec de tâche Celery.")[:1000],
    )
