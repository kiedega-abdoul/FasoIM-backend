"""Tâches Celery et progression Redis du bloc activités."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from uuid import uuid4

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.access_context import (
    definir_affectation_courante_id,
    restaurer_affectation_courante_id,
)

from .repository import (
    CandidatActiviteRepository,
    EvaluationRepository,
    SeanceRepository,
)
from .service import (
    EvaluationService,
    NoteService,
    PresenceService,
    ResultatTraitementMasse,
)


class ProgressionActivitesService:
    """Stocke progression et verrous dans Redis via le cache Django."""

    EXPIRATION_PROGRESSION = 60 * 60 * 24
    EXPIRATION_VERROU = 60 * 60 * 3
    TAILLE_LOT = 100

    EN_ATTENTE = "EN_ATTENTE"
    EN_COURS = "EN_COURS"
    TERMINEE = "TERMINEE"
    ECHEC = "ECHEC"
    REFUSEE = "REFUSEE"

    @staticmethod
    def cle_progression(task_id):
        return f"activites:tache:{task_id}:progression"

    @staticmethod
    def cle_verrou(
        operation,
        *,
        cible,
        empreinte="",
    ):
        cle = f"activites:lock:{operation}:{cible}"
        if empreinte:
            cle = f"{cle}:{empreinte}"
        return cle

    @classmethod
    def definir(
        cls,
        task_id,
        *,
        operation,
        statut,
        progression=0,
        message="",
        total=0,
        traites=0,
        crees=0,
        mis_a_jour=0,
        dispenses=0,
        bloques_medicaux=0,
        ignores=0,
        erreurs=0,
        resultat=None,
    ):
        donnees = {
            "task_id": str(task_id),
            "operation": str(operation),
            "statut": str(statut),
            "progression": max(
                0,
                min(int(progression or 0), 100),
            ),
            "message": str(message or ""),
            "total": max(0, int(total or 0)),
            "traites": max(0, int(traites or 0)),
            "crees": max(0, int(crees or 0)),
            "mis_a_jour": max(
                0,
                int(mis_a_jour or 0),
            ),
            "dispenses": max(0, int(dispenses or 0)),
            "bloques_medicaux": max(
                0,
                int(bloques_medicaux or 0),
            ),
            "ignores": max(0, int(ignores or 0)),
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
    def lire(cls, task_id):
        return cache.get(cls.cle_progression(task_id)) or {
            "task_id": str(task_id),
            "operation": "",
            "statut": cls.EN_ATTENTE,
            "progression": 0,
            "message": (
                "Aucune progression disponible pour cette tâche."
            ),
            "total": 0,
            "traites": 0,
            "crees": 0,
            "mis_a_jour": 0,
            "dispenses": 0,
            "bloques_medicaux": 0,
            "ignores": 0,
            "erreurs": 0,
            "resultat": None,
        }

    @classmethod
    @contextmanager
    def verrou(
        cls,
        operation,
        *,
        cible,
        empreinte="",
    ):
        cle = cls.cle_verrou(
            operation,
            cible=cible,
            empreinte=empreinte,
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


def _task_id(tache):
    return str(
        getattr(getattr(tache, "request", None), "id", None)
        or uuid4()
    )


def _acteur(acteur_id):
    acteur = get_user_model().objects.filter(
        id=acteur_id,
        is_active=True,
        deleted_at__isnull=True,
    ).first()
    if acteur is None:
        raise ValidationError(
            "L'acteur demandé est introuvable ou inactif."
        )
    return acteur


def _lots(valeurs, taille):
    for index in range(0, len(valeurs), taille):
        yield valeurs[index:index + taille]


def _empreinte(valeurs):
    if not valeurs:
        return "vide"

    texte = ",".join(
        str(valeur)
        for valeur in valeurs
    )
    return sha256(
        texte.encode("utf-8")
    ).hexdigest()[:20]


def _fusionner(cumuls, resultat):
    donnees = (
        resultat.en_dict()
        if isinstance(resultat, ResultatTraitementMasse)
        else dict(resultat)
    )
    for champ in (
        "demandes",
        "traites",
        "crees",
        "mis_a_jour",
        "dispenses",
        "bloques_medicaux",
        "ignores",
        "erreurs",
    ):
        cumuls[champ] = (
            cumuls.get(champ, 0)
            + int(donnees.get(champ, 0))
        )

    cumuls.setdefault("identifiants_ignores", []).extend(
        donnees.get("identifiants_ignores", [])
    )
    cumuls.setdefault("details", {}).update(
        donnees.get("details", {})
    )
    return cumuls


def _mettre_progression(
    task_id,
    *,
    operation,
    total,
    cumuls,
    message,
):
    traites = cumuls.get("traites", 0)
    pourcentage = (
        100
        if total == 0
        else int((traites / total) * 100)
    )
    return ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.EN_COURS,
        progression=pourcentage,
        message=message,
        total=total,
        traites=traites,
        crees=cumuls.get("crees", 0),
        mis_a_jour=cumuls.get("mis_a_jour", 0),
        dispenses=cumuls.get("dispenses", 0),
        bloques_medicaux=cumuls.get(
            "bloques_medicaux",
            0,
        ),
        ignores=cumuls.get("ignores", 0),
        erreurs=cumuls.get("erreurs", 0),
    )


def _terminer(
    task_id,
    *,
    operation,
    total,
    cumuls,
    message,
):
    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.TERMINEE,
        progression=100,
        message=message,
        total=total,
        traites=cumuls.get("traites", 0),
        crees=cumuls.get("crees", 0),
        mis_a_jour=cumuls.get("mis_a_jour", 0),
        dispenses=cumuls.get("dispenses", 0),
        bloques_medicaux=cumuls.get(
            "bloques_medicaux",
            0,
        ),
        ignores=cumuls.get("ignores", 0),
        erreurs=cumuls.get("erreurs", 0),
        resultat=cumuls,
    )
    return {
        "ok": True,
        "task_id": task_id,
        "operation": operation,
        **cumuls,
    }


def _refuser(
    task_id,
    *,
    operation,
    total,
    message,
):
    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.REFUSEE,
        progression=100,
        message=message,
        total=total,
    )
    return {
        "ok": False,
        "task_id": task_id,
        "operation": operation,
        "message": message,
    }


def _echouer(
    task_id,
    *,
    operation,
    total,
    cumuls,
    erreur,
):
    message = str(erreur)
    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.ECHEC,
        progression=100,
        message=message,
        total=total,
        traites=cumuls.get("traites", 0),
        crees=cumuls.get("crees", 0),
        mis_a_jour=cumuls.get("mis_a_jour", 0),
        dispenses=cumuls.get("dispenses", 0),
        bloques_medicaux=cumuls.get(
            "bloques_medicaux",
            0,
        ),
        ignores=cumuls.get("ignores", 0),
        erreurs=cumuls.get("erreurs", 0) + 1,
        resultat=cumuls,
    )
    raise erreur


@shared_task(
    bind=True,
    name=(
        "activites.tasks."
        "ouvrir_et_preparer_feuille_presence_task"
    ),
)
def ouvrir_et_preparer_feuille_presence_task(
    self,
    seance_id,
    acteur_id,
    affectation_acteur_id,
):
    task_id = _task_id(self)
    operation = "ouvrir_et_preparer_feuille_presence"
    seance = SeanceRepository.get_by_id(seance_id)
    ids = CandidatActiviteRepository.ids_pour_seance(
        seance
    )
    total = len(ids)
    cumuls = {}

    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.EN_ATTENTE,
        message="Préparation de la feuille mise en attente.",
        total=total,
    )

    with ProgressionActivitesService.verrou(
        operation,
        cible=f"seance:{seance_id}",
    ) as acquis:
        if not acquis:
            return _refuser(
                task_id,
                operation=operation,
                total=total,
                message=(
                    "Une préparation de cette feuille "
                    "est déjà en cours."
                ),
            )

        token = definir_affectation_courante_id(
            int(affectation_acteur_id)
        )
        try:
            acteur = _acteur(acteur_id)
            PresenceService.ouvrir_feuille_presence(
                seance_id,
                acteur=acteur,
            )

            for lot_ids in _lots(
                ids,
                ProgressionActivitesService.TAILLE_LOT,
            ):
                resultat = (
                    PresenceService
                    .preparer_feuille_pour_affectations(
                        seance_id=seance_id,
                        affectation_centre_ids=lot_ids,
                        acteur=acteur,
                        verifier_acces=False,
                    )
                )
                _fusionner(cumuls, resultat)
                _mettre_progression(
                    task_id,
                    operation=operation,
                    total=total,
                    cumuls=cumuls,
                    message="Préparation de la feuille en cours.",
                )

            return _terminer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Feuille de présence préparée.",
            )
        except Exception as erreur:
            return _echouer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                erreur=erreur,
            )
        finally:
            restaurer_affectation_courante_id(token)


@shared_task(
    bind=True,
    name="activites.tasks.saisir_presences_masse_task",
)
def saisir_presences_masse_task(
    self,
    seance_id,
    lignes,
    acteur_id,
    affectation_acteur_id,
):
    task_id = _task_id(self)
    operation = "saisir_presences_masse"
    lignes = list(lignes or [])
    total = len(lignes)
    cumuls = {}
    empreinte = _empreinte(
        [
            ligne.get("affectation_centre_id")
            for ligne in lignes
        ]
    )

    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.EN_ATTENTE,
        message="Saisie massive mise en attente.",
        total=total,
    )

    with ProgressionActivitesService.verrou(
        operation,
        cible=f"seance:{seance_id}",
        empreinte=empreinte,
    ) as acquis:
        if not acquis:
            return _refuser(
                task_id,
                operation=operation,
                total=total,
                message="Une saisie identique est déjà en cours.",
            )

        token = definir_affectation_courante_id(
            int(affectation_acteur_id)
        )
        try:
            acteur = _acteur(acteur_id)
            for lot in _lots(
                lignes,
                ProgressionActivitesService.TAILLE_LOT,
            ):
                resultat = PresenceService.saisir_presences_lot(
                    seance_id=seance_id,
                    lignes=lot,
                    acteur=acteur,
                )
                _fusionner(cumuls, resultat)
                _mettre_progression(
                    task_id,
                    operation=operation,
                    total=total,
                    cumuls=cumuls,
                    message="Saisie des présences en cours.",
                )

            return _terminer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Saisie massive des présences terminée.",
            )
        except Exception as erreur:
            return _echouer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                erreur=erreur,
            )
        finally:
            restaurer_affectation_courante_id(token)


@shared_task(
    bind=True,
    name=(
        "activites.tasks."
        "valider_feuilles_presence_masse_task"
    ),
)
def valider_feuilles_presence_masse_task(
    self,
    seance_ids,
    acteur_id,
    cloturer=False,
):
    task_id = _task_id(self)
    operation = "valider_feuilles_presence_masse"
    seance_ids = list(dict.fromkeys(seance_ids or []))
    total = len(seance_ids)
    cumuls = {
        "demandes": total,
        "traites": 0,
        "mis_a_jour": 0,
        "erreurs": 0,
        "details": {},
    }
    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.EN_ATTENTE,
        message="Validation massive mise en attente.",
        total=total,
    )

    with ProgressionActivitesService.verrou(
        operation,
        cible="seances",
        empreinte=_empreinte(seance_ids),
    ) as acquis:
        if not acquis:
            return _refuser(
                task_id,
                operation=operation,
                total=total,
                message=(
                    "Une validation identique est déjà en cours."
                ),
            )

        try:
            acteur = _acteur(acteur_id)
            for seance_id in seance_ids:
                try:
                    PresenceService.valider_feuille_presence(
                        seance_id,
                        acteur=acteur,
                    )
                    if cloturer:
                        PresenceService.cloturer_feuille_presence(
                            seance_id,
                            acteur=acteur,
                        )
                    cumuls["mis_a_jour"] += 1
                except ValidationError as exc:
                    cumuls["erreurs"] += 1
                    cumuls["details"][str(seance_id)] = str(exc)

                cumuls["traites"] += 1
                _mettre_progression(
                    task_id,
                    operation=operation,
                    total=total,
                    cumuls=cumuls,
                    message="Validation des feuilles en cours.",
                )

            return _terminer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Validation des feuilles terminée.",
            )
        except Exception as erreur:
            return _echouer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                erreur=erreur,
            )


@shared_task(
    bind=True,
    name="activites.tasks.saisir_notes_masse_task",
)
def saisir_notes_masse_task(
    self,
    evaluation_id,
    lignes,
    acteur_id,
):
    task_id = _task_id(self)
    operation = "saisir_notes_masse"
    lignes = list(lignes or [])
    total = len(lignes)
    cumuls = {}
    empreinte = _empreinte(
        [
            ligne.get("affectation_centre_id")
            for ligne in lignes
        ]
    )
    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.EN_ATTENTE,
        message="Saisie massive des notes mise en attente.",
        total=total,
    )

    with ProgressionActivitesService.verrou(
        operation,
        cible=f"evaluation:{evaluation_id}",
        empreinte=empreinte,
    ) as acquis:
        if not acquis:
            return _refuser(
                task_id,
                operation=operation,
                total=total,
                message="Une saisie identique est déjà en cours.",
            )

        try:
            acteur = _acteur(acteur_id)
            for lot in _lots(
                lignes,
                ProgressionActivitesService.TAILLE_LOT,
            ):
                resultat = NoteService.saisir_notes_lot(
                    evaluation_id=evaluation_id,
                    lignes=lot,
                    acteur=acteur,
                )
                _fusionner(cumuls, resultat)
                _mettre_progression(
                    task_id,
                    operation=operation,
                    total=total,
                    cumuls=cumuls,
                    message="Saisie des notes en cours.",
                )

            return _terminer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Saisie massive des notes terminée.",
            )
        except Exception as erreur:
            return _echouer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                erreur=erreur,
            )


@shared_task(
    bind=True,
    name="activites.tasks.valider_resultats_masse_task",
)
def valider_resultats_masse_task(
    self,
    evaluation_ids,
    acteur_id,
):
    task_id = _task_id(self)
    operation = "valider_resultats_masse"
    evaluation_ids = list(
        dict.fromkeys(evaluation_ids or [])
    )
    total = len(evaluation_ids)
    cumuls = {
        "demandes": total,
        "traites": 0,
        "mis_a_jour": 0,
        "erreurs": 0,
        "details": {},
    }
    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.EN_ATTENTE,
        message="Validation des résultats mise en attente.",
        total=total,
    )

    with ProgressionActivitesService.verrou(
        operation,
        cible="evaluations",
        empreinte=_empreinte(evaluation_ids),
    ) as acquis:
        if not acquis:
            return _refuser(
                task_id,
                operation=operation,
                total=total,
                message=(
                    "Une validation identique est déjà en cours."
                ),
            )

        try:
            acteur = _acteur(acteur_id)
            for evaluation_id in evaluation_ids:
                try:
                    EvaluationService.valider_resultats(
                        evaluation_id,
                        acteur=acteur,
                    )
                    cumuls["mis_a_jour"] += 1
                except ValidationError as exc:
                    cumuls["erreurs"] += 1
                    cumuls["details"][
                        str(evaluation_id)
                    ] = str(exc)

                cumuls["traites"] += 1
                _mettre_progression(
                    task_id,
                    operation=operation,
                    total=total,
                    cumuls=cumuls,
                    message="Validation des résultats en cours.",
                )

            return _terminer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Validation des résultats terminée.",
            )
        except Exception as erreur:
            return _echouer(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                erreur=erreur,
            )


@shared_task(
    bind=True,
    name="activites.tasks.recalculer_taux_presence_task",
)
def recalculer_taux_presence_task(
    self,
    session_id,
    affectation_centre_ids,
    acteur_id,
):
    task_id = _task_id(self)
    operation = "recalculer_taux_presence"
    ids = list(dict.fromkeys(affectation_centre_ids or []))
    total = len(ids)
    cumuls = {
        "demandes": total,
        "traites": 0,
        "mis_a_jour": 0,
        "erreurs": 0,
        "details": {},
    }
    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.EN_ATTENTE,
        message="Recalcul des taux mis en attente.",
        total=total,
    )

    try:
        acteur = _acteur(acteur_id)
        for affectation_id in ids:
            try:
                resultat = PresenceService.calculer_taux_presence(
                    affectation_centre_id=affectation_id,
                    session_id=session_id,
                    acteur=acteur,
                )
                cumuls["details"][str(affectation_id)] = {
                    cle: str(valeur)
                    if hasattr(valeur, "as_tuple")
                    else valeur
                    for cle, valeur in resultat.items()
                }
                cumuls["mis_a_jour"] += 1
            except ValidationError as exc:
                cumuls["erreurs"] += 1
                cumuls["details"][str(affectation_id)] = str(exc)

            cumuls["traites"] += 1
            _mettre_progression(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Recalcul des taux en cours.",
            )

        return _terminer(
            task_id,
            operation=operation,
            total=total,
            cumuls=cumuls,
            message="Recalcul des taux terminé.",
        )
    except Exception as erreur:
        return _echouer(
            task_id,
            operation=operation,
            total=total,
            cumuls=cumuls,
            erreur=erreur,
        )


@shared_task(
    bind=True,
    name="activites.tasks.recalculer_moyennes_task",
)
def recalculer_moyennes_task(
    self,
    session_id,
    affectation_centre_ids,
    acteur_id,
):
    task_id = _task_id(self)
    operation = "recalculer_moyennes"
    ids = list(dict.fromkeys(affectation_centre_ids or []))
    total = len(ids)
    cumuls = {
        "demandes": total,
        "traites": 0,
        "mis_a_jour": 0,
        "erreurs": 0,
        "details": {},
    }
    ProgressionActivitesService.definir(
        task_id,
        operation=operation,
        statut=ProgressionActivitesService.EN_ATTENTE,
        message="Recalcul des moyennes mis en attente.",
        total=total,
    )

    try:
        acteur = _acteur(acteur_id)
        for affectation_id in ids:
            try:
                resultat = NoteService.calculer_moyenne(
                    affectation_centre_id=affectation_id,
                    session_id=session_id,
                    acteur=acteur,
                )
                cumuls["details"][str(affectation_id)] = {
                    cle: str(valeur)
                    if hasattr(valeur, "as_tuple")
                    else valeur
                    for cle, valeur in resultat.items()
                }
                cumuls["mis_a_jour"] += 1
            except ValidationError as exc:
                cumuls["erreurs"] += 1
                cumuls["details"][str(affectation_id)] = str(exc)

            cumuls["traites"] += 1
            _mettre_progression(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Recalcul des moyennes en cours.",
            )

        return _terminer(
            task_id,
            operation=operation,
            total=total,
            cumuls=cumuls,
            message="Recalcul des moyennes terminé.",
        )
    except Exception as erreur:
        return _echouer(
            task_id,
            operation=operation,
            total=total,
            cumuls=cumuls,
            erreur=erreur,
        )
