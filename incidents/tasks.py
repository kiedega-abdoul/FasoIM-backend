from __future__ import annotations

from contextlib import contextmanager
import sys
from uuid import uuid4

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .detectors.registry import detecteurs, get_detecteur
from .service import AlerteAutomatiqueService


class ProgressionIncidentsService:
    EXPIRATION_PROGRESSION = 60 * 60 * 24
    EXPIRATION_VERROU = 60 * 5
    EXPIRATION_DEBOUNCE = getattr(
        settings, "INCIDENTS_SCAN_DEBOUNCE_SECONDS", 30
    )

    EN_ATTENTE = "EN_ATTENTE"
    EN_COURS = "EN_COURS"
    TERMINEE = "TERMINEE"
    TERMINEE_AVEC_ERREURS = "TERMINEE_AVEC_ERREURS"
    ECHEC = "ECHEC"
    REFUSEE = "REFUSEE"

    @staticmethod
    def cle_progression(task_id):
        return f"incidents:tache:{task_id}:progression"

    @staticmethod
    def cle_verrou(module):
        return f"incidents:lock:scan:{module}"

    @staticmethod
    def cle_debounce(module):
        return f"incidents:debounce:scan:{module}"

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
        try:
            cache.set(
                cls.cle_progression(task_id),
                donnees,
                timeout=cls.EXPIRATION_PROGRESSION,
            )
        except Exception:
            # La surveillance ne doit jamais faire échouer une action métier si
            # Redis est momentanément indisponible.
            pass
        return donnees

    @classmethod
    def lire(cls, task_id):
        try:
            valeur = cache.get(cls.cle_progression(task_id))
        except Exception:
            valeur = None
        return valeur or {
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
    def verrou(cls, module):
        cle = cls.cle_verrou(module)
        jeton = uuid4().hex
        try:
            acquis = cache.add(cle, jeton, timeout=cls.EXPIRATION_VERROU)
        except Exception:
            acquis = True
        try:
            yield acquis
        finally:
            if acquis:
                try:
                    if cache.get(cle) == jeton:
                        cache.delete(cle)
                except Exception:
                    pass

    @classmethod
    def reserver_controle_immediat(cls, module):
        try:
            return cache.add(
                cls.cle_debounce(module),
                uuid4().hex,
                timeout=cls.EXPIRATION_DEBOUNCE,
            )
        except Exception:
            return True


def _task_id(tache):
    return str(getattr(tache.request, "id", None) or uuid4())


def _message_exception(exception):
    if hasattr(exception, "message_dict"):
        return str(exception.message_dict)
    if hasattr(exception, "messages"):
        return str(exception.messages)
    return str(exception)


@shared_task(bind=True, name="incidents.scanner_module")
def scanner_module_task(self, *, module):
    task_id = _task_id(self)
    operation = f"scan_{module}"
    ProgressionIncidentsService.definir(
        task_id,
        operation=operation,
        statut=ProgressionIncidentsService.EN_ATTENTE,
        progression=0,
        message="Scan enregistré.",
    )
    detecteur = get_detecteur(module)
    if not detecteur:
        return ProgressionIncidentsService.definir(
            task_id,
            operation=operation,
            statut=ProgressionIncidentsService.ECHEC,
            progression=100,
            message="Module de détection inconnu.",
            erreur=f"Aucun détecteur pour {module}.",
        )

    with ProgressionIncidentsService.verrou(module) as acquis:
        if not acquis:
            return ProgressionIncidentsService.definir(
                task_id,
                operation=operation,
                statut=ProgressionIncidentsService.REFUSEE,
                progression=0,
                message="Un scan identique est déjà en cours.",
            )
        try:
            ProgressionIncidentsService.definir(
                task_id,
                operation=operation,
                statut=ProgressionIncidentsService.EN_COURS,
                progression=20,
                message=f"Contrôle du module {module} en cours.",
            )
            resultat = AlerteAutomatiqueService.executer_detecteur(detecteur).en_dict()
            return ProgressionIncidentsService.definir(
                task_id,
                operation=operation,
                statut=ProgressionIncidentsService.TERMINEE,
                progression=100,
                message="Scan terminé.",
                resultat=resultat,
            )
        except Exception as exception:
            return ProgressionIncidentsService.definir(
                task_id,
                operation=operation,
                statut=ProgressionIncidentsService.ECHEC,
                progression=100,
                message="Le scan a échoué.",
                erreur=_message_exception(exception),
            )


@shared_task(bind=True, name="incidents.scanner_integrite_global")
def scanner_integrite_global_task(self):
    task_id = _task_id(self)
    operation = "scan_global"
    liste = list(detecteurs())
    ProgressionIncidentsService.definir(
        task_id,
        operation=operation,
        statut=ProgressionIncidentsService.EN_ATTENTE,
        progression=0,
        message="Scan global enregistré.",
    )

    with ProgressionIncidentsService.verrou("global") as acquis:
        if not acquis:
            return ProgressionIncidentsService.definir(
                task_id,
                operation=operation,
                statut=ProgressionIncidentsService.REFUSEE,
                progression=0,
                message="Un scan global est déjà en cours.",
            )

        resultats = []
        erreurs = []
        for index, detecteur in enumerate(liste, start=1):
            progression = int(((index - 1) / max(len(liste), 1)) * 90) + 5
            ProgressionIncidentsService.definir(
                task_id,
                operation=operation,
                statut=ProgressionIncidentsService.EN_COURS,
                progression=progression,
                message=f"Contrôle du module {detecteur.module}.",
                resultat={"modules_termines": resultats},
            )
            try:
                resultats.append(
                    AlerteAutomatiqueService.executer_detecteur(detecteur).en_dict()
                )
            except Exception as exception:
                erreurs.append(
                    {
                        "module": detecteur.module,
                        "erreur": _message_exception(exception),
                    }
                )

        escalades = 0
        try:
            escalades = AlerteAutomatiqueService.escalader_retards()
        except Exception as exception:
            erreurs.append({"module": "escalade", "erreur": _message_exception(exception)})

        statut = (
            ProgressionIncidentsService.TERMINEE_AVEC_ERREURS
            if erreurs
            else ProgressionIncidentsService.TERMINEE
        )
        return ProgressionIncidentsService.definir(
            task_id,
            operation=operation,
            statut=statut,
            progression=100,
            message=(
                "Scan global terminé avec certaines erreurs."
                if erreurs
                else "Scan global terminé avec succès."
            ),
            resultat={
                "modules": resultats,
                "erreurs": erreurs,
                "incidents_escalades": escalades,
            },
        )


@shared_task(bind=True, name="incidents.escalader_retards")
def escalader_retards_task(self):
    task_id = _task_id(self)
    try:
        total = AlerteAutomatiqueService.escalader_retards()
        return ProgressionIncidentsService.definir(
            task_id,
            operation="escalade_retards",
            statut=ProgressionIncidentsService.TERMINEE,
            progression=100,
            message="Escalade automatique terminée.",
            resultat={"incidents_escalades": total},
        )
    except Exception as exception:
        return ProgressionIncidentsService.definir(
            task_id,
            operation="escalade_retards",
            statut=ProgressionIncidentsService.ECHEC,
            progression=100,
            message="L'escalade automatique a échoué.",
            erreur=_message_exception(exception),
        )


def programmer_scan_module_apres_commit(module):
    """Programme un contrôle ciblé sans porter la validation métier.

    Les migrations, les tests et les commandes de seed sont volontairement exclus :
    un scan global périodique contrôlera l'état une fois ces opérations terminées.
    """

    if not getattr(settings, "INCIDENTS_CONTROLES_CIBLES_ACTIFS", True):
        return
    commande = sys.argv[1] if len(sys.argv) > 1 else ""
    if commande in {"makemigrations", "migrate", "test", "seed_accounts", "collectstatic"}:
        return

    def envoyer():
        if not ProgressionIncidentsService.reserver_controle_immediat(module):
            return
        try:
            scanner_module_task.delay(module=module)
        except Exception:
            # Le scan périodique de cinq minutes prendra le relais.
            pass

    transaction.on_commit(envoyer)
