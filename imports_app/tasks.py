from contextlib import contextmanager

from celery import shared_task
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ImportOfficiel
from .repository import (
    CorrespondanceColonneImportRepository,
    ErreurImportRepository,
    ImportOfficielRepository,
    LigneImportRepository,
)
from .service import ImportOfficielService, ValidationImportService


class ProgressionImportService:
    """Petite couche Redis/cache pour suivre les traitements d'import.

    Redis sert ici de stockage temporaire : progression, message et verrou.
    PostgreSQL reste la source officielle des données de l'import.
    """

    EXPIRATION_PROGRESSION = 60 * 60
    EXPIRATION_VERROU = 60 * 30

    @staticmethod
    def cle_progression(import_id):
        return f"imports:import:{import_id}:progression"

    @staticmethod
    def cle_verrou(import_id, operation):
        return f"imports:import:{import_id}:lock:{operation}"

    @classmethod
    def definir(cls, import_id, *, pourcentage=0, message="", operation=""):
        donnees = {
            "import_id": import_id,
            "operation": operation,
            "pourcentage": max(0, min(int(pourcentage or 0), 100)),
            "message": message or "",
            "updated_at": timezone.now().isoformat(),
        }
        cache.set(cls.cle_progression(import_id), donnees, timeout=cls.EXPIRATION_PROGRESSION)
        return donnees

    @classmethod
    def lire(cls, import_id):
        return cache.get(cls.cle_progression(import_id)) or {
            "import_id": import_id,
            "operation": "",
            "pourcentage": 0,
            "message": "Aucune progression disponible.",
        }

    @classmethod
    def terminer(cls, import_id, *, operation="", message="Traitement terminé."):
        return cls.definir(import_id, pourcentage=100, message=message, operation=operation)

    @classmethod
    def echouer(cls, import_id, *, operation="", message="Traitement en échec."):
        return cls.definir(import_id, pourcentage=100, message=message, operation=operation)

    @classmethod
    @contextmanager
    def verrou(cls, import_id, operation):
        cle = cls.cle_verrou(import_id, operation)
        acquis = cache.add(cle, timezone.now().isoformat(), timeout=cls.EXPIRATION_VERROU)
        try:
            yield acquis
        finally:
            if acquis:
                cache.delete(cle)


def _message_exception(erreur):
    if isinstance(erreur, ValidationError):
        return str(erreur.message_dict if hasattr(erreur, "message_dict") else erreur.messages)
    return str(erreur)


def _mettre_import_en_echec_si_possible(import_id, message):
    import_officiel = ImportOfficielRepository.get_by_id(import_id)
    if not import_officiel:
        return None
    return ImportOfficielRepository.mettre_a_jour_statut(
        import_officiel,
        ImportOfficiel.Statut.ECHEC,
        message=message,
    )


@shared_task(bind=True, name="imports_app.tasks.lire_colonnes_import_task")
def lire_colonnes_import_task(self, import_id):
    """Analyse asynchrone de la structure du fichier importé.

    Cette tâche lit seulement la structure : type fichier, feuille Excel utile,
    séparateur CSV, ligne d'entête probable et colonnes détectées. Elle ne crée
    pas encore les lignes, car l'utilisateur doit d'abord confirmer la
    correspondance des colonnes.
    """

    operation = "lecture_colonnes"
    with ProgressionImportService.verrou(import_id, operation) as verrou_acquis:
        if not verrou_acquis:
            return {
                "ok": False,
                "import_id": import_id,
                "operation": operation,
                "message": "Lecture déjà en cours pour cet import.",
            }

        try:
            ProgressionImportService.definir(
                import_id,
                operation=operation,
                pourcentage=10,
                message="Lecture de la structure du fichier...",
            )
            import_officiel = ImportOfficielService.analyser_colonnes(import_id)
            ProgressionImportService.terminer(
                import_id,
                operation=operation,
                message="Colonnes détectées. Correspondance requise.",
            )
            return {
                "ok": True,
                "import_id": import_id,
                "statut": import_officiel.statut,
                "colonnes_detectees": import_officiel.colonnes_detectees,
                "parametres_lecture": import_officiel.parametres_lecture,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            _mettre_import_en_echec_si_possible(import_id, message)
            ProgressionImportService.echouer(import_id, operation=operation, message=message)
            raise


@shared_task(bind=True, name="imports_app.tasks.valider_lignes_import_task")
def valider_lignes_import_task(self, import_id):
    """Lecture complète et validation asynchrones des lignes d'un import."""

    operation = "validation_lignes"
    with ProgressionImportService.verrou(import_id, operation) as verrou_acquis:
        if not verrou_acquis:
            return {
                "ok": False,
                "import_id": import_id,
                "operation": operation,
                "message": "Validation déjà en cours pour cet import.",
            }

        try:
            ProgressionImportService.definir(
                import_id,
                operation=operation,
                pourcentage=10,
                message="Validation des lignes en cours...",
            )
            import_officiel = ValidationImportService.valider_lignes(import_id)
            ProgressionImportService.terminer(
                import_id,
                operation=operation,
                message="Validation des lignes terminée.",
            )
            return {
                "ok": True,
                "import_id": import_id,
                "statut": import_officiel.statut,
                "total_lignes": import_officiel.total_lignes,
                "lignes_valides": import_officiel.lignes_valides,
                "lignes_erreur": import_officiel.lignes_erreur,
                "lignes_ignorees": import_officiel.lignes_ignorees,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            _mettre_import_en_echec_si_possible(import_id, message)
            ProgressionImportService.echouer(import_id, operation=operation, message=message)
            raise


@shared_task(bind=True, name="imports_app.tasks.confirmer_import_task")
def confirmer_import_task(self, import_id, confirme_par_id=None):
    """Confirmation finale d'un import vers les tables immerges.

    Cette tâche transforme les lignes valides en sources métier
    ImmergeExamen/ImmergeConcours/ImmergeSelectionne/InscriptionVolontaire,
    puis crée la ligne centrale Immerge avec code FasoIM et QR textuel.
    """

    operation = "confirmation_import"
    with ProgressionImportService.verrou(import_id, operation) as verrou_acquis:
        if not verrou_acquis:
            return {
                "ok": False,
                "import_id": import_id,
                "operation": operation,
                "message": "Confirmation déjà en cours pour cet import.",
            }

        try:
            ProgressionImportService.definir(
                import_id,
                operation=operation,
                pourcentage=10,
                message="Confirmation de l'import vers les immergés...",
            )

            confirme_par = None
            if confirme_par_id:
                from django.contrib.auth import get_user_model

                confirme_par = get_user_model().objects.filter(id=confirme_par_id).first()

            from immerges.service import ImportVersImmergeService

            resultat = ImportVersImmergeService.confirmer_import(
                import_id,
                confirme_par=confirme_par,
            )

            ProgressionImportService.terminer(
                import_id,
                operation=operation,
                message="Confirmation terminée.",
            )
            import_officiel = resultat["import_officiel"]
            return {
                "ok": resultat["lignes_erreur"] == 0,
                "import_id": import_id,
                "operation": operation,
                "statut": import_officiel.statut,
                "lignes_traitees": resultat["lignes_traitees"],
                "lignes_importees": resultat["lignes_importees"],
                "lignes_erreur": resultat["lignes_erreur"],
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImportService.echouer(import_id, operation=operation, message=message)
            raise


@shared_task(bind=True, name="imports_app.tasks.supprimer_import_logiquement_task")
def supprimer_import_logiquement_task(self, import_id):
    """Suppression logique asynchrone d'un import et de ses dépendances."""

    operation = "suppression_logique"
    with ProgressionImportService.verrou(import_id, operation) as verrou_acquis:
        if not verrou_acquis:
            return {
                "ok": False,
                "import_id": import_id,
                "operation": operation,
                "message": "Suppression déjà en cours pour cet import.",
            }

        import_officiel = ImportOfficielRepository.get_by_id(import_id)
        if not import_officiel:
            return {
                "ok": False,
                "import_id": import_id,
                "operation": operation,
                "message": "Import officiel introuvable ou déjà supprimé.",
            }

        ProgressionImportService.definir(
            import_id,
            operation=operation,
            pourcentage=10,
            message="Suppression logique de l'import...",
        )

        with transaction.atomic():
            ProgressionImportService.definir(
                import_id,
                operation=operation,
                pourcentage=30,
                message="Suppression logique des erreurs...",
            )
            erreurs_supprimees = ErreurImportRepository.supprimer_logiquement_par_import(import_officiel)

            ProgressionImportService.definir(
                import_id,
                operation=operation,
                pourcentage=50,
                message="Suppression logique des lignes...",
            )
            lignes_supprimees = LigneImportRepository.supprimer_logiquement_par_import(import_officiel)

            ProgressionImportService.definir(
                import_id,
                operation=operation,
                pourcentage=70,
                message="Suppression logique des correspondances...",
            )
            correspondances_supprimees = CorrespondanceColonneImportRepository.supprimer_logiquement_par_import(import_officiel)

            ProgressionImportService.definir(
                import_id,
                operation=operation,
                pourcentage=90,
                message="Suppression logique du dossier d'import...",
            )
            import_supprime = ImportOfficielRepository.soft_delete(import_officiel)

        ProgressionImportService.terminer(
            import_id,
            operation=operation,
            message="Suppression logique terminée.",
        )
        return {
            "ok": True,
            "import_id": import_id,
            "operation": operation,
            "import_supprime": import_supprime,
            "correspondances_supprimees": correspondances_supprimees,
            "lignes_supprimees": lignes_supprimees,
            "erreurs_supprimees": erreurs_supprimees,
        }
