"""Tâches Celery du module affectations.

Les permissions sont vérifiées synchroniquement par l'API avant le lancement.
Celery exécute seulement les opérations massives déjà autorisées. Redis, via
le cache Django, conserve les verrous et la progression temporaire ; PostgreSQL
reste la source officielle des affectations.
"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from uuid import uuid4

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from .service import (
    AffectationCentreService,
    AffectationRegionaleService,
)


class ProgressionAffectationService:
    """Stocke dans Redis la progression visible par le frontend."""

    EXPIRATION_PROGRESSION = 60 * 60 * 24
    EXPIRATION_VERROU = 60 * 60 * 2

    STATUT_EN_ATTENTE = "EN_ATTENTE"
    STATUT_EN_COURS = "EN_COURS"
    STATUT_TERMINEE = "TERMINEE"
    STATUT_ECHEC = "ECHEC"
    STATUT_REFUSEE = "REFUSEE"

    @staticmethod
    def cle_progression(task_id: str) -> str:
        return f"affectations:tache:{task_id}:progression"

    @staticmethod
    def cle_verrou(operation: str, portee: str) -> str:
        return f"affectations:lock:{operation}:{portee}"

    @classmethod
    def definir(
        cls,
        task_id: str,
        *,
        operation: str,
        statut: str,
        progression: int = 0,
        message: str = "",
        total: int = 0,
        traites: int = 0,
        proposes: int = 0,
        restants: int = 0,
        erreurs: int = 0,
        resultat: dict | None = None,
    ) -> dict:
        donnees = {
            "task_id": str(task_id),
            "operation": str(operation),
            "statut": str(statut),
            "progression": max(0, min(int(progression or 0), 100)),
            "message": str(message or ""),
            "total": max(0, int(total or 0)),
            "traites": max(0, int(traites or 0)),
            "proposes": max(0, int(proposes or 0)),
            "restants": max(0, int(restants or 0)),
            "erreurs": max(0, int(erreurs or 0)),
            "resultat": resultat,
            "updated_at": timezone.now().isoformat(),
        }
        cache.set(
            cls.cle_progression(task_id),
            donnees,
            timeout=cls.EXPIRATION_PROGRESSION,
        )
        return donnees

    @classmethod
    def lire(cls, task_id: str) -> dict:
        return cache.get(cls.cle_progression(task_id)) or {
            "task_id": str(task_id),
            "operation": "",
            "statut": cls.STATUT_EN_ATTENTE,
            "progression": 0,
            "message": "Aucune progression disponible pour cette tâche.",
            "total": 0,
            "traites": 0,
            "proposes": 0,
            "restants": 0,
            "erreurs": 0,
            "resultat": None,
        }

    @classmethod
    @contextmanager
    def verrou(cls, operation: str, portee: str):
        """Empêche deux workers de traiter simultanément la même portée."""

        cle = cls.cle_verrou(operation, portee)
        acquis = cache.add(
            cle,
            timezone.now().isoformat(),
            timeout=cls.EXPIRATION_VERROU,
        )
        try:
            yield acquis
        finally:
            if acquis:
                cache.delete(cle)


def _task_id(tache) -> str:
    return str(getattr(getattr(tache, "request", None), "id", None) or uuid4())


def _acteur_ou_none(acteur_id):
    if not acteur_id:
        return None
    return get_user_model().objects.filter(pk=acteur_id).first()


def _message_exception(erreur: Exception) -> str:
    if isinstance(erreur, ValidationError):
        if hasattr(erreur, "message_dict"):
            return str(erreur.message_dict)
        return str(erreur.messages)
    return str(erreur)


def _empreinte_ids(ids) -> str:
    valeurs = ",".join(str(int(valeur)) for valeur in sorted(set(ids)))
    return sha256(valeurs.encode("utf-8")).hexdigest()[:20]


def _resultat_tache(task_id: str, operation: str, resultat: dict) -> dict:
    return {
        "ok": True,
        "task_id": task_id,
        "operation": operation,
        **resultat,
    }


@shared_task(
    bind=True,
    name="affectations.tasks.proposer_affectations_regionales_task",
)
def proposer_affectations_regionales_task(
    self,
    session_id: int,
    nombre: int,
    acteur_id: int | None = None,
    forcer_reliquat: bool = False,
):
    """Prépare un lot régional que la DGAS devra vérifier puis valider."""

    task_id = _task_id(self)
    operation = "proposition_affectations_regionales"
    portee = f"session:{int(session_id)}"

    ProgressionAffectationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionAffectationService.STATUT_EN_ATTENTE,
        progression=0,
        message="Tâche de proposition régionale mise en attente.",
        total=nombre,
        restants=nombre,
    )

    with ProgressionAffectationService.verrou(operation, portee) as acquis:
        if not acquis:
            message = (
                "Une proposition régionale est déjà en cours pour cette session."
            )
            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_REFUSEE,
                progression=100,
                message=message,
                total=nombre,
                restants=nombre,
            )
            return {
                "ok": False,
                "task_id": task_id,
                "operation": operation,
                "message": message,
            }

        try:
            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_EN_COURS,
                progression=10,
                message="Sélection du lot d'immergés sans affectation régionale.",
                total=nombre,
                restants=nombre,
            )

            resultat = AffectationRegionaleService.proposer_lot(
                session_id=int(session_id),
                nombre=int(nombre),
                acteur=_acteur_ou_none(acteur_id),
                forcer_reliquat=bool(forcer_reliquat),
            ).en_dict()

            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_TERMINEE,
                progression=100,
                message=(
                    f"{resultat['propositions_creees']} proposition(s) "
                    "régionale(s) prête(s) à vérifier."
                ),
                total=resultat["candidats_pris"],
                traites=resultat["candidats_pris"],
                proposes=resultat["propositions_creees"],
                restants=resultat["candidats_restants"],
                erreurs=(
                    len(resultat["sans_source"])
                    + len(resultat["sans_destination"])
                ),
                resultat=resultat,
            )
            return _resultat_tache(task_id, operation, resultat)
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_ECHEC,
                progression=100,
                message=message,
                total=nombre,
                restants=nombre,
                erreurs=1,
            )
            raise


@shared_task(
    bind=True,
    name="affectations.tasks.proposer_affectations_centres_task",
)
def proposer_affectations_centres_task(
    self,
    session_id: int,
    region_id: int,
    nombre: int,
    acteur_id: int | None = None,
):
    """Prépare un lot de centres que le Directeur régional devra valider."""

    task_id = _task_id(self)
    operation = "proposition_affectations_centres"
    portee = f"session:{int(session_id)}:region:{int(region_id)}"

    ProgressionAffectationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionAffectationService.STATUT_EN_ATTENTE,
        progression=0,
        message="Tâche de proposition aux centres mise en attente.",
        total=nombre,
        restants=nombre,
    )

    with ProgressionAffectationService.verrou(operation, portee) as acquis:
        if not acquis:
            message = (
                "Une proposition de centres est déjà en cours pour cette région."
            )
            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_REFUSEE,
                progression=100,
                message=message,
                total=nombre,
                restants=nombre,
            )
            return {
                "ok": False,
                "task_id": task_id,
                "operation": operation,
                "message": message,
            }

        try:
            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_EN_COURS,
                progression=10,
                message="Recherche des immergés sans centre dans la région.",
                total=nombre,
                restants=nombre,
            )

            resultat = AffectationCentreService.proposer_lot(
                session_id=int(session_id),
                region_id=int(region_id),
                nombre=int(nombre),
                acteur=_acteur_ou_none(acteur_id),
            ).en_dict()

            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_TERMINEE,
                progression=100,
                message=(
                    f"{resultat['propositions_creees']} proposition(s) "
                    "de centre prête(s) à vérifier."
                ),
                total=resultat["candidats_pris"],
                traites=resultat["candidats_pris"],
                proposes=resultat["propositions_creees"],
                restants=resultat["candidats_restants"],
                erreurs=(
                    len(resultat["sans_source"])
                    + len(resultat["sans_destination"])
                ),
                resultat=resultat,
            )
            return _resultat_tache(task_id, operation, resultat)
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_ECHEC,
                progression=100,
                message=message,
                total=nombre,
                restants=nombre,
                erreurs=1,
            )
            raise


def _executer_action_lot(
    *,
    task,
    operation: str,
    affectation_ids,
    action,
    acteur_id=None,
    motif="",
):
    ids = list(dict.fromkeys(int(valeur) for valeur in affectation_ids))
    task_id = _task_id(task)
    portee = f"lot:{_empreinte_ids(ids)}"

    ProgressionAffectationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionAffectationService.STATUT_EN_ATTENTE,
        progression=0,
        message="Action de lot mise en attente.",
        total=len(ids),
        restants=len(ids),
    )

    with ProgressionAffectationService.verrou(operation, portee) as acquis:
        if not acquis:
            message = "Une action identique est déjà en cours sur ce lot."
            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_REFUSEE,
                progression=100,
                message=message,
                total=len(ids),
                restants=len(ids),
            )
            return {
                "ok": False,
                "task_id": task_id,
                "operation": operation,
                "message": message,
            }

        try:
            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_EN_COURS,
                progression=20,
                message="Traitement du lot en cours.",
                total=len(ids),
                restants=len(ids),
            )

            kwargs = {"motif": motif}
            if acteur_id is not None:
                kwargs["acteur"] = _acteur_ou_none(acteur_id)

            affectations = action(ids, **kwargs)
            resultat = {
                "demandes": len(ids),
                "candidats_pris": len(affectations),
                "propositions_creees": 0,
                "candidats_restants": max(0, len(ids) - len(affectations)),
                "sans_source": [],
                "sans_destination": [],
                "affectation_ids": [objet.id for objet in affectations],
                "details": {
                    "operation": operation,
                    "affectations_traitees": len(affectations),
                },
            }

            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_TERMINEE,
                progression=100,
                message=f"{len(affectations)} affectation(s) traitée(s).",
                total=len(ids),
                traites=len(affectations),
                restants=max(0, len(ids) - len(affectations)),
                resultat=resultat,
            )
            return _resultat_tache(task_id, operation, resultat)
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionAffectationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionAffectationService.STATUT_ECHEC,
                progression=100,
                message=message,
                total=len(ids),
                restants=len(ids),
                erreurs=1,
            )
            raise


@shared_task(
    bind=True,
    name="affectations.tasks.valider_affectations_regionales_task",
)
def valider_affectations_regionales_task(
    self,
    affectation_ids,
    acteur_id: int | None = None,
    motif: str = "",
):
    return _executer_action_lot(
        task=self,
        operation="validation_affectations_regionales",
        affectation_ids=affectation_ids,
        action=AffectationRegionaleService.valider_lot,
        acteur_id=acteur_id,
        motif=motif,
    )


@shared_task(
    bind=True,
    name="affectations.tasks.rejeter_affectations_regionales_task",
)
def rejeter_affectations_regionales_task(
    self,
    affectation_ids,
    motif: str,
):
    return _executer_action_lot(
        task=self,
        operation="rejet_affectations_regionales",
        affectation_ids=affectation_ids,
        action=AffectationRegionaleService.rejeter_lot,
        motif=motif,
    )


@shared_task(
    bind=True,
    name="affectations.tasks.valider_affectations_centres_task",
)
def valider_affectations_centres_task(
    self,
    affectation_ids,
    acteur_id: int | None = None,
    motif: str = "",
):
    return _executer_action_lot(
        task=self,
        operation="validation_affectations_centres",
        affectation_ids=affectation_ids,
        action=AffectationCentreService.valider_lot,
        acteur_id=acteur_id,
        motif=motif,
    )


@shared_task(
    bind=True,
    name="affectations.tasks.rejeter_affectations_centres_task",
)
def rejeter_affectations_centres_task(
    self,
    affectation_ids,
    motif: str,
):
    return _executer_action_lot(
        task=self,
        operation="rejet_affectations_centres",
        affectation_ids=affectation_ids,
        action=AffectationCentreService.rejeter_lot,
        motif=motif,
    )


