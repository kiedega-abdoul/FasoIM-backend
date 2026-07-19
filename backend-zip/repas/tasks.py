"""Traitements massifs Celery et progression Redis du module repas."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from .service import RavitaillementService, RepasService


class ProgressionRepasService:
    EXPIRATION_PROGRESSION = 60 * 60 * 24
    EXPIRATION_VERROU = 60 * 60 * 3

    EN_ATTENTE = "EN_ATTENTE"
    EN_COURS = "EN_COURS"
    TERMINEE = "TERMINEE"
    ECHEC = "ECHEC"
    REFUSEE = "REFUSEE"

    @staticmethod
    def cle_progression(task_id):
        return f"repas:tache:{task_id}:progression"

    @staticmethod
    def cle_verrou(operation, *, portee, identifiant):
        return f"repas:lock:{operation}:{portee}:{identifiant}"

    @classmethod
    def definir(
        cls,
        task_id,
        *,
        operation,
        statut,
        progression=0,
        message="",
        resultat=None,
        erreur="",
    ):
        donnees = {
            "task_id": str(task_id),
            "operation": str(operation),
            "statut": str(statut),
            "progression": max(0, min(int(progression or 0), 100)),
            "message": str(message or ""),
            "resultat": resultat,
            "erreur": str(erreur or ""),
            "updated_at": timezone.now().isoformat(),
        }
        cache.set(
            cls.cle_progression(task_id),
            donnees,
            timeout=cls.EXPIRATION_PROGRESSION,
        )
        return donnees

    @classmethod
    def lire(cls, task_id):
        return cache.get(cls.cle_progression(task_id)) or {
            "task_id": str(task_id),
            "operation": "",
            "statut": cls.EN_ATTENTE,
            "progression": 0,
            "message": "Aucune progression n'est encore disponible.",
            "resultat": None,
            "erreur": "",
        }

    @classmethod
    @contextmanager
    def verrou(cls, operation, *, portee, identifiant):
        cle = cls.cle_verrou(
            operation, portee=portee, identifiant=identifiant
        )
        jeton = uuid4().hex
        acquis = cache.add(cle, jeton, timeout=cls.EXPIRATION_VERROU)
        try:
            yield acquis
        finally:
            if acquis and cache.get(cle) == jeton:
                cache.delete(cle)


def _task_id(tache):
    return str(getattr(tache.request, "id", None) or uuid4())


def _acteur(acteur_id):
    acteur = get_user_model().objects.filter(
        id=acteur_id,
        is_active=True,
        deleted_at__isnull=True,
    ).first()
    if acteur is None:
        raise ValidationError("L'acteur est introuvable ou inactif.")
    return acteur


def _message_exception(exception):
    if isinstance(exception, ValidationError):
        if hasattr(exception, "message_dict"):
            return str(exception.message_dict)
        return str(exception.messages)
    return str(exception)


def _executer(
    tache,
    *,
    operation,
    portee,
    identifiant,
    travail,
):
    task_id = _task_id(tache)
    ProgressionRepasService.definir(
        task_id,
        operation=operation,
        statut=ProgressionRepasService.EN_ATTENTE,
        progression=0,
        message="Traitement enregistré.",
    )
    with ProgressionRepasService.verrou(
        operation, portee=portee, identifiant=identifiant
    ) as acquis:
        if not acquis:
            return ProgressionRepasService.definir(
                task_id,
                operation=operation,
                statut=ProgressionRepasService.REFUSEE,
                progression=0,
                message="Une opération identique est déjà en cours.",
            )
        try:
            ProgressionRepasService.definir(
                task_id,
                operation=operation,
                statut=ProgressionRepasService.EN_COURS,
                progression=20,
                message="Contrôles terminés, traitement en cours.",
            )
            resultat = travail()
            if hasattr(resultat, "en_dict"):
                resultat = resultat.en_dict()
            return ProgressionRepasService.definir(
                task_id,
                operation=operation,
                statut=ProgressionRepasService.TERMINEE,
                progression=100,
                message="Traitement terminé avec succès.",
                resultat=resultat,
            )
        except Exception as exception:
            message = _message_exception(exception)
            ProgressionRepasService.definir(
                task_id,
                operation=operation,
                statut=ProgressionRepasService.ECHEC,
                progression=100,
                message="Le traitement a échoué.",
                erreur=message,
            )
            raise


@shared_task(bind=True, name="repas.preparer_suivis")
def preparer_suivis_repas_task(self, *, repas_id, acteur_id):
    return _executer(
        self,
        operation="preparation_suivis",
        portee="repas",
        identifiant=repas_id,
        travail=lambda: RepasService.preparer_comptages(
            repas_id, acteur=_acteur(acteur_id)
        ),
    )


@shared_task(bind=True, name="repas.actualiser_sante")
def actualiser_besoins_sante_repas_task(self, *, repas_id, acteur_id):
    def travail():
        repas = RepasService.actualiser_besoins_sante(
            repas_id, acteur=_acteur(acteur_id)
        )
        return {
            "repas_id": repas.id,
            "nombre_standard_prevu": repas.nombre_standard_prevu,
            "synthese": repas.synthese_restrictions_alimentaires,
            "statut_controle_sante": repas.statut_controle_sante,
        }

    return _executer(
        self,
        operation="actualisation_sante",
        portee="repas",
        identifiant=repas_id,
        travail=travail,
    )


@shared_task(bind=True, name="repas.cloturer_distribution")
def cloturer_repas_task(self, *, repas_id, acteur_id):
    def travail():
        repas = RepasService.cloturer(repas_id, acteur=_acteur(acteur_id))
        return {"repas_id": repas.id, "statut": repas.statut}

    return _executer(
        self,
        operation="cloture",
        portee="repas",
        identifiant=repas_id,
        travail=travail,
    )


@shared_task(bind=True, name="repas.generer_donnees_rapport")
def generer_rapport_repas_task(self, *, acteur_id, filtres):
    session_id = filtres.get("session_id")
    return _executer(
        self,
        operation="rapport",
        portee="session",
        identifiant=session_id,
        travail=lambda: RepasService.statistiques(
            acteur=_acteur(acteur_id), **filtres
        ),
    )


@shared_task(bind=True, name="repas.consolider_denrees")
def consolider_besoins_denrees_task(
    self, *, acteur_id, session_id, region_id=None
):
    return _executer(
        self,
        operation="consolidation_denrees",
        portee="session",
        identifiant=session_id,
        travail=lambda: RavitaillementService.consolider(
            acteur=_acteur(acteur_id),
            session_id=session_id,
            region_id=region_id,
        ),
    )
