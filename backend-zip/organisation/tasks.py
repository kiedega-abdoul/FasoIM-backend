"""Tâches Celery du module organisation.

Les services contiennent les règles métier et les transactions. Les tâches
Celery exécutent les traitements lourds, posent les verrous Redis et publient
la progression temporaire. PostgreSQL reste la source officielle.
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
    HebergementService,
    OrganisationCentreService,
    VisiteMedicaleOrganisationService,
)


class ProgressionOrganisationService:
    """État Redis des traitements massifs du module organisation."""

    EXPIRATION_PROGRESSION = 60 * 60 * 24
    EXPIRATION_VERROU = 60 * 60 * 3

    STATUT_EN_ATTENTE = "EN_ATTENTE"
    STATUT_EN_COURS = "EN_COURS"
    STATUT_TERMINEE = "TERMINEE"
    STATUT_ECHEC = "ECHEC"
    STATUT_REFUSEE = "REFUSEE"

    @staticmethod
    def cle_progression(task_id: str) -> str:
        return f"organisation:tache:{task_id}:progression"

    @staticmethod
    def cle_verrou(
        operation: str,
        *,
        session_id=None,
        centre_id=None,
        portee=None,
    ) -> str:
        morceaux = ["organisation", "lock", str(operation)]
        if session_id is not None:
            morceaux.extend(["session", str(session_id)])
        if centre_id is not None:
            morceaux.extend(["centre", str(centre_id)])
        if portee:
            morceaux.extend(["portee", str(portee)])
        return ":".join(morceaux)

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
        crees: int = 0,
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
            "crees": max(0, int(crees or 0)),
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
            "crees": 0,
            "restants": 0,
            "erreurs": 0,
            "resultat": None,
        }

    @classmethod
    @contextmanager
    def verrou(
        cls,
        operation: str,
        *,
        session_id=None,
        centre_id=None,
        portee=None,
    ):
        cle = cls.cle_verrou(
            operation,
            session_id=session_id,
            centre_id=centre_id,
            portee=portee,
        )
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
    return str(
        getattr(getattr(tache, "request", None), "id", None)
        or uuid4()
    )


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
    valeurs = ",".join(
        str(int(valeur))
        for valeur in sorted(set(ids))
    )
    return sha256(valeurs.encode("utf-8")).hexdigest()[:20]


def _reponse_succes(task_id: str, operation: str, resultat: dict) -> dict:
    return {
        "ok": True,
        "task_id": task_id,
        "operation": operation,
        **resultat,
    }


def _refuser_tache(
    *,
    task_id: str,
    operation: str,
    message: str,
    total: int = 0,
):
    ProgressionOrganisationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionOrganisationService.STATUT_REFUSEE,
        progression=100,
        message=message,
        total=total,
        restants=total,
    )
    return {
        "ok": False,
        "task_id": task_id,
        "operation": operation,
        "message": message,
    }


@shared_task(
    bind=True,
    name="organisation.tasks.generer_sections_groupes_task",
)
def generer_sections_groupes_task(
    self,
    session_id: int,
    centre_id: int,
    recreer: bool = False,
):
    task_id = _task_id(self)
    operation = "generer_sections_groupes"

    ProgressionOrganisationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionOrganisationService.STATUT_EN_ATTENTE,
        progression=0,
        message="Génération des structures mise en attente.",
    )

    with ProgressionOrganisationService.verrou(
        operation,
        session_id=session_id,
        centre_id=centre_id,
    ) as acquis:
        if not acquis:
            return _refuser_tache(
                task_id=task_id,
                operation=operation,
                message=(
                    "Une génération des sections et groupes est déjà en "
                    "cours pour ce centre."
                ),
            )

        try:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_EN_COURS,
                progression=20,
                message="Calcul du nombre de sections et groupes.",
            )

            resultat = OrganisationCentreService.generer_sections_groupes(
                session_id=int(session_id),
                centre_id=int(centre_id),
                recreer=bool(recreer),
            ).en_dict()

            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_TERMINEE,
                progression=100,
                message="Sections et groupes générés.",
                total=resultat["demandes"],
                traites=resultat["traites"],
                crees=resultat["crees"],
                restants=resultat["restants"],
                resultat=resultat,
            )
            return _reponse_succes(task_id, operation, resultat)
        except Exception as erreur:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_ECHEC,
                progression=100,
                message=_message_exception(erreur),
                erreurs=1,
            )
            raise


@shared_task(
    bind=True,
    name="organisation.tasks.proposer_affectations_groupes_task",
)
def proposer_affectations_groupes_task(
    self,
    session_id: int,
    centre_id: int,
    nombre: int,
    acteur_id: int | None = None,
):
    task_id = _task_id(self)
    operation = "proposer_affectations_groupes"

    ProgressionOrganisationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionOrganisationService.STATUT_EN_ATTENTE,
        progression=0,
        message="Proposition des groupes mise en attente.",
        total=nombre,
        restants=nombre,
    )

    with ProgressionOrganisationService.verrou(
        operation,
        session_id=session_id,
        centre_id=centre_id,
    ) as acquis:
        if not acquis:
            return _refuser_tache(
                task_id=task_id,
                operation=operation,
                message=(
                    "Une proposition de groupes est déjà en cours pour "
                    "ce centre."
                ),
                total=nombre,
            )

        try:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_EN_COURS,
                progression=15,
                message="Sélection du lot d'immergés à organiser.",
                total=nombre,
                restants=nombre,
            )

            resultat = (
                OrganisationCentreService.proposer_affectations_groupes(
                    session_id=int(session_id),
                    centre_id=int(centre_id),
                    nombre=int(nombre),
                    acteur=_acteur_ou_none(acteur_id),
                ).en_dict()
            )

            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_TERMINEE,
                progression=100,
                message=(
                    f"{resultat['crees']} proposition(s) de groupe créée(s)."
                ),
                total=resultat["demandes"],
                traites=resultat["traites"],
                crees=resultat["crees"],
                restants=resultat["restants"],
                erreurs=len(resultat["sans_destination"]),
                resultat=resultat,
            )
            return _reponse_succes(task_id, operation, resultat)
        except Exception as erreur:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_ECHEC,
                progression=100,
                message=_message_exception(erreur),
                total=nombre,
                restants=nombre,
                erreurs=1,
            )
            raise


@shared_task(
    bind=True,
    name="organisation.tasks.proposer_attributions_lits_task",
)
def proposer_attributions_lits_task(
    self,
    session_id: int,
    centre_id: int,
    nombre: int,
    acteur_id: int | None = None,
):
    task_id = _task_id(self)
    operation = "proposer_attributions_lits"

    ProgressionOrganisationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionOrganisationService.STATUT_EN_ATTENTE,
        progression=0,
        message="Proposition des lits mise en attente.",
        total=nombre,
        restants=nombre,
    )

    with ProgressionOrganisationService.verrou(
        operation,
        session_id=session_id,
        centre_id=centre_id,
    ) as acquis:
        if not acquis:
            return _refuser_tache(
                task_id=task_id,
                operation=operation,
                message=(
                    "Une proposition de lits est déjà en cours pour ce centre."
                ),
                total=nombre,
            )

        try:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_EN_COURS,
                progression=15,
                message="Sélection des immergés et lits disponibles.",
                total=nombre,
                restants=nombre,
            )

            resultat = HebergementService.proposer_attributions_lits(
                session_id=int(session_id),
                centre_id=int(centre_id),
                nombre=int(nombre),
                acteur=_acteur_ou_none(acteur_id),
            ).en_dict()

            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_TERMINEE,
                progression=100,
                message=(
                    f"{resultat['crees']} proposition(s) de lit créée(s)."
                ),
                total=resultat["demandes"],
                traites=resultat["traites"],
                crees=resultat["crees"],
                restants=resultat["restants"],
                erreurs=len(resultat["sans_destination"]),
                resultat=resultat,
            )
            return _reponse_succes(task_id, operation, resultat)
        except Exception as erreur:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_ECHEC,
                progression=100,
                message=_message_exception(erreur),
                total=nombre,
                restants=nombre,
                erreurs=1,
            )
            raise


def _executer_action_lot(
    *,
    task,
    operation: str,
    ids,
    action,
    acteur_id=None,
    observations="",
):
    ids = list(dict.fromkeys(int(valeur) for valeur in ids))
    task_id = _task_id(task)
    portee = _empreinte_ids(ids)

    ProgressionOrganisationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionOrganisationService.STATUT_EN_ATTENTE,
        progression=0,
        message="Action de lot mise en attente.",
        total=len(ids),
        restants=len(ids),
    )

    with ProgressionOrganisationService.verrou(
        operation,
        portee=portee,
    ) as acquis:
        if not acquis:
            return _refuser_tache(
                task_id=task_id,
                operation=operation,
                message="Une action identique est déjà en cours sur ce lot.",
                total=len(ids),
            )

        try:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_EN_COURS,
                progression=25,
                message="Traitement du lot en cours.",
                total=len(ids),
                restants=len(ids),
            )

            kwargs = {"observations": observations}
            if acteur_id is not None:
                kwargs["acteur"] = _acteur_ou_none(acteur_id)

            objets = action(ids, **kwargs)
            resultat = {
                "demandes": len(ids),
                "traites": len(objets),
                "crees": 0,
                "restants": max(0, len(ids) - len(objets)),
                "sans_destination": [],
                "ids_crees": [objet.id for objet in objets],
                "details": {
                    "operation": operation,
                    "objets_traites": len(objets),
                },
            }

            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_TERMINEE,
                progression=100,
                message=f"{len(objets)} élément(s) traité(s).",
                total=len(ids),
                traites=len(objets),
                restants=max(0, len(ids) - len(objets)),
                resultat=resultat,
            )
            return _reponse_succes(task_id, operation, resultat)
        except Exception as erreur:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_ECHEC,
                progression=100,
                message=_message_exception(erreur),
                total=len(ids),
                restants=len(ids),
                erreurs=1,
            )
            raise


@shared_task(
    bind=True,
    name="organisation.tasks.valider_affectations_groupes_task",
)
def valider_affectations_groupes_task(
    self,
    affectation_ids,
    acteur_id: int | None = None,
    observations: str = "",
):
    return _executer_action_lot(
        task=self,
        operation="valider_affectations_groupes",
        ids=affectation_ids,
        action=OrganisationCentreService.valider_affectations_groupes,
        acteur_id=acteur_id,
        observations=observations,
    )


@shared_task(
    bind=True,
    name="organisation.tasks.rejeter_affectations_groupes_task",
)
def rejeter_affectations_groupes_task(
    self,
    affectation_ids,
    observations: str,
):
    return _executer_action_lot(
        task=self,
        operation="rejeter_affectations_groupes",
        ids=affectation_ids,
        action=OrganisationCentreService.rejeter_affectations_groupes,
        observations=observations,
    )


@shared_task(
    bind=True,
    name="organisation.tasks.valider_attributions_lits_task",
)
def valider_attributions_lits_task(
    self,
    attribution_ids,
    acteur_id: int | None = None,
    observations: str = "",
):
    return _executer_action_lot(
        task=self,
        operation="valider_attributions_lits",
        ids=attribution_ids,
        action=HebergementService.valider_attributions_lits,
        acteur_id=acteur_id,
        observations=observations,
    )


@shared_task(
    bind=True,
    name="organisation.tasks.rejeter_attributions_lits_task",
)
def rejeter_attributions_lits_task(
    self,
    attribution_ids,
    observations: str,
):
    return _executer_action_lot(
        task=self,
        operation="rejeter_attributions_lits",
        ids=attribution_ids,
        action=HebergementService.rejeter_attributions_lits,
        observations=observations,
    )


@shared_task(
    bind=True,
    name="organisation.tasks.appliquer_resultats_medicaux_task",
)
def appliquer_resultats_medicaux_task(
    self,
    session_id: int,
    centre_id: int,
    resultats,
):
    """Applique en arrière-plan les décisions médicales déjà enregistrées.

    Chaque élément doit contenir affectation_centre_id, resultat et peut
    contenir observations, reorganiser_groupe et reorganiser_lit.
    """

    task_id = _task_id(self)
    operation = "appliquer_resultats_medicaux"
    resultats = list(resultats or [])
    total = len(resultats)

    ProgressionOrganisationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionOrganisationService.STATUT_EN_ATTENTE,
        progression=0,
        message="Application des résultats médicaux mise en attente.",
        total=total,
        restants=total,
    )

    with ProgressionOrganisationService.verrou(
        operation,
        session_id=session_id,
        centre_id=centre_id,
    ) as acquis:
        if not acquis:
            return _refuser_tache(
                task_id=task_id,
                operation=operation,
                message=(
                    "L'application des résultats médicaux est déjà en cours "
                    "pour ce centre."
                ),
                total=total,
            )

        traites = 0
        erreurs = []
        details = []

        try:
            for index, donnees in enumerate(resultats, start=1):
                try:
                    detail = (
                        VisiteMedicaleOrganisationService.appliquer_resultat(
                            affectation_centre_id=int(
                                donnees["affectation_centre_id"]
                            ),
                            resultat=donnees["resultat"],
                            observations=donnees.get("observations", ""),
                            reorganiser_groupe=bool(
                                donnees.get("reorganiser_groupe", True)
                            ),
                            reorganiser_lit=bool(
                                donnees.get("reorganiser_lit", True)
                            ),
                        )
                    )
                    details.append(detail)
                    traites += 1
                except Exception as erreur:
                    erreurs.append(
                        {
                            "affectation_centre_id": donnees.get(
                                "affectation_centre_id"
                            ),
                            "message": _message_exception(erreur),
                        }
                    )

                if index == total or index % 10 == 0:
                    ProgressionOrganisationService.definir(
                        task_id,
                        operation=operation,
                        statut=(
                            ProgressionOrganisationService.STATUT_EN_COURS
                        ),
                        progression=(
                            int(index * 100 / total) if total else 100
                        ),
                        message=(
                            f"{index}/{total} résultat(s) médical(aux) "
                            "examiné(s)."
                        ),
                        total=total,
                        traites=traites,
                        restants=max(0, total - index),
                        erreurs=len(erreurs),
                    )

            resultat = {
                "demandes": total,
                "traites": traites,
                "crees": 0,
                "restants": max(0, total - traites),
                "sans_destination": [],
                "ids_crees": [],
                "details": {
                    "resultats": details,
                    "erreurs": erreurs,
                },
            }

            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_TERMINEE,
                progression=100,
                message=(
                    f"{traites} résultat(s) médical(aux) appliqué(s)."
                ),
                total=total,
                traites=traites,
                restants=max(0, total - traites),
                erreurs=len(erreurs),
                resultat=resultat,
            )
            return _reponse_succes(task_id, operation, resultat)
        except Exception as erreur:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_ECHEC,
                progression=100,
                message=_message_exception(erreur),
                total=total,
                traites=traites,
                restants=max(0, total - traites),
                erreurs=len(erreurs) + 1,
            )
            raise


@shared_task(
    bind=True,
    name="organisation.tasks.reorganiser_aptes_sous_reserve_task",
)
def reorganiser_aptes_sous_reserve_task(
    self,
    session_id: int,
    centre_id: int,
    affectation_centre_ids=None,
    acteur_id: int | None = None,
):
    task_id = _task_id(self)
    operation = "reorganiser_aptes_sous_reserve"

    ProgressionOrganisationService.definir(
        task_id,
        operation=operation,
        statut=ProgressionOrganisationService.STATUT_EN_ATTENTE,
        progression=0,
        message="Réorganisation médicale mise en attente.",
    )

    with ProgressionOrganisationService.verrou(
        operation,
        session_id=session_id,
        centre_id=centre_id,
    ) as acquis:
        if not acquis:
            return _refuser_tache(
                task_id=task_id,
                operation=operation,
                message=(
                    "Une réorganisation médicale est déjà en cours pour "
                    "ce centre."
                ),
            )

        try:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_EN_COURS,
                progression=20,
                message=(
                    "Recherche de nouvelles places pour les aptes sous "
                    "réserve."
                ),
            )

            resultat = (
                VisiteMedicaleOrganisationService
                .reorganiser_aptitudes_sous_reserve(
                    session_id=int(session_id),
                    centre_id=int(centre_id),
                    affectation_centre_ids=affectation_centre_ids,
                    acteur=_acteur_ou_none(acteur_id),
                )
                .en_dict()
            )

            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_TERMINEE,
                progression=100,
                message=(
                    f"{resultat['crees']} nouvelle(s) proposition(s) "
                    "médicale(s) créée(s)."
                ),
                total=resultat["demandes"],
                traites=resultat["traites"],
                crees=resultat["crees"],
                restants=resultat["restants"],
                erreurs=len(resultat["sans_destination"]),
                resultat=resultat,
            )
            return _reponse_succes(task_id, operation, resultat)
        except Exception as erreur:
            ProgressionOrganisationService.definir(
                task_id,
                operation=operation,
                statut=ProgressionOrganisationService.STATUT_ECHEC,
                progression=100,
                message=_message_exception(erreur),
                erreurs=1,
            )
            raise


__all__ = [
    "ProgressionOrganisationService",
    "generer_sections_groupes_task",
    "proposer_affectations_groupes_task",
    "proposer_attributions_lits_task",
    "valider_affectations_groupes_task",
    "rejeter_affectations_groupes_task",
    "valider_attributions_lits_task",
    "rejeter_attributions_lits_task",
    "appliquer_resultats_medicaux_task",
    "reorganiser_aptes_sous_reserve_task",
]
