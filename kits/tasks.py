"""Tâches Celery et progression Redis du module kits."""

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
from .repository import CandidatRemiseKitRepository
from .service import (
    ControleAccesKitsService,
    RemiseKitService,
)


class ProgressionKitsService:
    EXPIRATION_PROGRESSION = 60 * 60 * 24
    EXPIRATION_VERROU = 60 * 60 * 3
    TAILLE_LOT = 100

    STATUT_EN_ATTENTE = "EN_ATTENTE"
    STATUT_EN_COURS = "EN_COURS"
    STATUT_TERMINEE = "TERMINEE"
    STATUT_ECHEC = "ECHEC"
    STATUT_REFUSEE = "REFUSEE"

    @staticmethod
    def cle_progression(task_id):
        return f"kits:tache:{task_id}:progression"

    @staticmethod
    def cle_verrou(
        operation,
        *,
        session_id,
        centre_id,
        portee="",
    ):
        morceaux = [
            "kits",
            "lock",
            str(operation),
            "session",
            str(session_id),
            "centre",
            str(centre_id),
        ]
        if portee:
            morceaux.extend(["portee", str(portee)])
        return ":".join(morceaux)

    @classmethod
    def definir(
        cls,
        task_id,
        *,
        operation,
        statut,
        progression=0,
        message="",
        total_immerges=0,
        immerges_traites=0,
        remises_creees=0,
        remises_validees=0,
        remises_annulees=0,
        bloques_medicaux=0,
        sans_article=0,
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
            "total_immerges": max(
                0,
                int(total_immerges or 0),
            ),
            "immerges_traites": max(
                0,
                int(immerges_traites or 0),
            ),
            "remises_creees": max(
                0,
                int(remises_creees or 0),
            ),
            "remises_validees": max(
                0,
                int(remises_validees or 0),
            ),
            "remises_annulees": max(
                0,
                int(remises_annulees or 0),
            ),
            "bloques_medicaux": max(
                0,
                int(bloques_medicaux or 0),
            ),
            "sans_article": max(
                0,
                int(sans_article or 0),
            ),
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
            "statut": cls.STATUT_EN_ATTENTE,
            "progression": 0,
            "message": (
                "Aucune progression disponible pour cette tâche."
            ),
            "total_immerges": 0,
            "immerges_traites": 0,
            "remises_creees": 0,
            "remises_validees": 0,
            "remises_annulees": 0,
            "bloques_medicaux": 0,
            "sans_article": 0,
            "erreurs": 0,
            "resultat": None,
        }

    @classmethod
    @contextmanager
    def verrou(
        cls,
        operation,
        *,
        session_id,
        centre_id,
        portee="",
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


def _message_exception(erreur):
    if isinstance(erreur, ValidationError):
        if hasattr(erreur, "message_dict"):
            return str(erreur.message_dict)
        return str(erreur.messages)
    return str(erreur)


def _empreinte_ids(ids):
    if not ids:
        return "tous"

    valeurs = ",".join(
        str(int(valeur))
        for valeur in sorted(set(ids))
    )
    return sha256(
        valeurs.encode("utf-8")
    ).hexdigest()[:20]


def _lots(valeurs, taille):
    for index in range(0, len(valeurs), taille):
        yield valeurs[index:index + taille]


def _fusionner(cumuls, resultat):
    donnees = resultat.en_dict()
    for champ in (
        "demandes",
        "traites",
        "eligibles",
        "remises_creees",
        "remises_validees",
        "remises_annulees",
        "bloques_medicaux",
        "sans_article",
        "erreurs",
    ):
        cumuls[champ] = (
            cumuls.get(champ, 0)
            + int(donnees.get(champ, 0))
        )

    cumuls.setdefault(
        "affectations_ignorees",
        [],
    ).extend(
        donnees.get("affectations_ignorees", [])
    )
    return cumuls


def _progression(
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
    return ProgressionKitsService.definir(
        task_id,
        operation=operation,
        statut=(
            ProgressionKitsService.STATUT_EN_COURS
        ),
        progression=pourcentage,
        message=message,
        total_immerges=total,
        immerges_traites=traites,
        remises_creees=cumuls.get(
            "remises_creees",
            0,
        ),
        remises_validees=cumuls.get(
            "remises_validees",
            0,
        ),
        remises_annulees=cumuls.get(
            "remises_annulees",
            0,
        ),
        bloques_medicaux=cumuls.get(
            "bloques_medicaux",
            0,
        ),
        sans_article=cumuls.get(
            "sans_article",
            0,
        ),
        erreurs=cumuls.get("erreurs", 0),
    )


def _refuser(
    *,
    task_id,
    operation,
    message,
    total=0,
):
    ProgressionKitsService.definir(
        task_id,
        operation=operation,
        statut=ProgressionKitsService.STATUT_REFUSEE,
        progression=100,
        message=message,
        total_immerges=total,
    )
    return {
        "ok": False,
        "task_id": task_id,
        "operation": operation,
        "message": message,
    }


def _terminer(
    *,
    task_id,
    operation,
    total,
    cumuls,
    message,
):
    ProgressionKitsService.definir(
        task_id,
        operation=operation,
        statut=ProgressionKitsService.STATUT_TERMINEE,
        progression=100,
        message=message,
        total_immerges=total,
        immerges_traites=cumuls.get("traites", 0),
        remises_creees=cumuls.get(
            "remises_creees",
            0,
        ),
        remises_validees=cumuls.get(
            "remises_validees",
            0,
        ),
        remises_annulees=cumuls.get(
            "remises_annulees",
            0,
        ),
        bloques_medicaux=cumuls.get(
            "bloques_medicaux",
            0,
        ),
        sans_article=cumuls.get(
            "sans_article",
            0,
        ),
        erreurs=cumuls.get("erreurs", 0),
        resultat=cumuls,
    )
    return {
        "ok": True,
        "task_id": task_id,
        "operation": operation,
        **cumuls,
    }


def _echouer(
    *,
    task_id,
    operation,
    total,
    cumuls,
    erreur,
):
    message = _message_exception(erreur)
    ProgressionKitsService.definir(
        task_id,
        operation=operation,
        statut=ProgressionKitsService.STATUT_ECHEC,
        progression=100,
        message=message,
        total_immerges=total,
        immerges_traites=cumuls.get("traites", 0),
        remises_creees=cumuls.get(
            "remises_creees",
            0,
        ),
        remises_validees=cumuls.get(
            "remises_validees",
            0,
        ),
        remises_annulees=cumuls.get(
            "remises_annulees",
            0,
        ),
        bloques_medicaux=cumuls.get(
            "bloques_medicaux",
            0,
        ),
        sans_article=cumuls.get(
            "sans_article",
            0,
        ),
        erreurs=cumuls.get("erreurs", 0) + 1,
        resultat=cumuls,
    )
    raise erreur


@shared_task(
    bind=True,
    name="kits.tasks.preparer_remises_centre_task",
)
def preparer_remises_centre_task(
    self,
    session_id,
    centre_id,
    acteur_id,
    affectation_centre_ids=None,
    article_kit_ids=None,
):
    task_id = _task_id(self)
    operation = "preparer_remises_centre"
    ids = CandidatRemiseKitRepository.ids(
        session_id=session_id,
        centre_id=centre_id,
        affectation_centre_ids=affectation_centre_ids,
    )
    total = len(ids)
    portee = (
        f"{_empreinte_ids(ids)}:"
        f"{_empreinte_ids(article_kit_ids)}"
    )

    ProgressionKitsService.definir(
        task_id,
        operation=operation,
        statut=ProgressionKitsService.STATUT_EN_ATTENTE,
        progression=0,
        message="Préparation des remises mise en attente.",
        total_immerges=total,
    )

    with ProgressionKitsService.verrou(
        operation,
        session_id=session_id,
        centre_id=centre_id,
        portee=portee,
    ) as acquis:
        if not acquis:
            return _refuser(
                task_id=task_id,
                operation=operation,
                message=(
                    "Une préparation identique est déjà "
                    "en cours pour ce centre."
                ),
                total=total,
            )

        cumuls = {}
        try:
            acteur = _acteur(acteur_id)
            ControleAccesKitsService.exiger(
                acteur,
                (
                    ControleAccesKitsService
                    .PREPARER_REMISES_MASSE
                ),
                session_id=session_id,
                centre_id=centre_id,
            )

            _progression(
                task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Préparation des lignes de remise.",
            )

            for lot_ids in _lots(
                ids,
                ProgressionKitsService.TAILLE_LOT,
            ):
                resultat = (
                    RemiseKitService.preparer_pour_affectations(
                        session_id=session_id,
                        centre_id=centre_id,
                        affectation_centre_ids=lot_ids,
                        acteur=acteur,
                        article_kit_ids=article_kit_ids,
                        verifier_acces=False,
                    )
                )
                _fusionner(cumuls, resultat)
                _progression(
                    task_id,
                    operation=operation,
                    total=total,
                    cumuls=cumuls,
                    message=(
                        "Préparation des remises en cours."
                    ),
                )

            return _terminer(
                task_id=task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Préparation des remises terminée.",
            )

        except Exception as erreur:
            return _echouer(
                task_id=task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                erreur=erreur,
            )


@shared_task(
    bind=True,
    name="kits.tasks.valider_remises_immerges_task",
)
def valider_remises_immerges_task(
    self,
    session_id,
    centre_id,
    acteur_id,
    affectation_acteur_id=None,
    affectation_centre_ids=None,
    article_kit_ids=None,
):
    task_id = _task_id(self)
    operation = "valider_remises_immerges"
    ids = CandidatRemiseKitRepository.ids(
        session_id=session_id,
        centre_id=centre_id,
        affectation_centre_ids=affectation_centre_ids,
    )
    total = len(ids)
    portee = (
        f"{_empreinte_ids(ids)}:"
        f"{_empreinte_ids(article_kit_ids)}"
    )

    ProgressionKitsService.definir(
        task_id,
        operation=operation,
        statut=ProgressionKitsService.STATUT_EN_ATTENTE,
        progression=0,
        message="Validation massive mise en attente.",
        total_immerges=total,
    )

    with ProgressionKitsService.verrou(
        operation,
        session_id=session_id,
        centre_id=centre_id,
        portee=portee,
    ) as acquis:
        if not acquis:
            return _refuser(
                task_id=task_id,
                operation=operation,
                message=(
                    "Une validation identique est déjà "
                    "en cours pour ce centre."
                ),
                total=total,
            )

        cumuls = {}
        try:
            acteur = _acteur(acteur_id)

            token = definir_affectation_courante_id(
                affectation_acteur_id
            )
            try:
                ControleAccesKitsService.exiger(
                    acteur,
                    (
                        ControleAccesKitsService
                        .VALIDER_REMISES_MASSE
                    ),
                    session_id=session_id,
                    centre_id=centre_id,
                )
            finally:
                restaurer_affectation_courante_id(token)

            for lot_ids in _lots(
                ids,
                ProgressionKitsService.TAILLE_LOT,
            ):
                resultat = (
                    RemiseKitService.valider_pour_affectations(
                        session_id=session_id,
                        centre_id=centre_id,
                        affectation_centre_ids=lot_ids,
                        acteur=acteur,
                        article_kit_ids=article_kit_ids,
                        verifier_acces=False,
                    )
                )
                _fusionner(cumuls, resultat)
                _progression(
                    task_id,
                    operation=operation,
                    total=total,
                    cumuls=cumuls,
                    message=(
                        "Validation massive des remises en cours."
                    ),
                )

            return _terminer(
                task_id=task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Validation massive terminée.",
            )

        except Exception as erreur:
            return _echouer(
                task_id=task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                erreur=erreur,
            )


@shared_task(
    bind=True,
    name="kits.tasks.annuler_remises_lot_task",
)
def annuler_remises_lot_task(
    self,
    session_id,
    centre_id,
    acteur_id,
    affectation_centre_ids,
    article_kit_ids=None,
):
    task_id = _task_id(self)
    operation = "annuler_remises_lot"
    ids = CandidatRemiseKitRepository.ids(
        session_id=session_id,
        centre_id=centre_id,
        affectation_centre_ids=affectation_centre_ids,
    )
    total = len(ids)
    portee = (
        f"{_empreinte_ids(ids)}:"
        f"{_empreinte_ids(article_kit_ids)}"
    )

    ProgressionKitsService.definir(
        task_id,
        operation=operation,
        statut=ProgressionKitsService.STATUT_EN_ATTENTE,
        progression=0,
        message="Annulation massive mise en attente.",
        total_immerges=total,
    )

    with ProgressionKitsService.verrou(
        operation,
        session_id=session_id,
        centre_id=centre_id,
        portee=portee,
    ) as acquis:
        if not acquis:
            return _refuser(
                task_id=task_id,
                operation=operation,
                message=(
                    "Une annulation identique est déjà "
                    "en cours pour ce centre."
                ),
                total=total,
            )

        cumuls = {}
        try:
            acteur = _acteur(acteur_id)
            ControleAccesKitsService.exiger(
                acteur,
                (
                    ControleAccesKitsService
                    .ANNULER_REMISES_MASSE
                ),
                session_id=session_id,
                centre_id=centre_id,
            )

            for lot_ids in _lots(
                ids,
                ProgressionKitsService.TAILLE_LOT,
            ):
                resultat = (
                    RemiseKitService.annuler_pour_affectations(
                        session_id=session_id,
                        centre_id=centre_id,
                        affectation_centre_ids=lot_ids,
                        acteur=acteur,
                        article_kit_ids=article_kit_ids,
                        verifier_acces=False,
                    )
                )
                _fusionner(cumuls, resultat)
                _progression(
                    task_id,
                    operation=operation,
                    total=total,
                    cumuls=cumuls,
                    message="Annulation massive en cours.",
                )

            return _terminer(
                task_id=task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                message="Annulation massive terminée.",
            )

        except Exception as erreur:
            return _echouer(
                task_id=task_id,
                operation=operation,
                total=total,
                cumuls=cumuls,
                erreur=erreur,
            )
