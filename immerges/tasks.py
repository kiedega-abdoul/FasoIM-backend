from contextlib import contextmanager

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Immerge, InscriptionVolontaire
from .repository import (
    ImmergeConcoursRepository,
    ImmergeExamenRepository,
    ImmergeRepository,
    ImmergeSelectionneRepository,
    InscriptionVolontaireRepository,
)
from .service import (
    CodeFasoIMService,
    ImmergeService,
    ImportVersImmergeService,
    InscriptionVolontaireService,
)


class ProgressionImmergeService:
    """Stockage temporaire Redis/cache pour les traitements lourds des immergés.

    PostgreSQL reste la source officielle des données.
    Redis sert seulement à suivre la progression et à empêcher deux traitements
    lourds identiques de tourner en même temps.
    """

    EXPIRATION_PROGRESSION = 60 * 60
    EXPIRATION_VERROU = 60 * 30

    @staticmethod
    def cle_progression(identifiant):
        return f"immerges:{identifiant}:progression"

    @staticmethod
    def cle_verrou(identifiant, operation):
        return f"immerges:{identifiant}:lock:{operation}"

    @classmethod
    def definir(cls, identifiant, *, operation="", pourcentage=0, message=""):
        donnees = {
            "identifiant": str(identifiant),
            "operation": operation or "",
            "pourcentage": max(0, min(int(pourcentage or 0), 100)),
            "message": message or "",
            "updated_at": timezone.now().isoformat(),
        }
        cache.set(cls.cle_progression(identifiant), donnees, timeout=cls.EXPIRATION_PROGRESSION)
        return donnees

    @classmethod
    def lire(cls, identifiant):
        return cache.get(cls.cle_progression(identifiant)) or {
            "identifiant": str(identifiant),
            "operation": "",
            "pourcentage": 0,
            "message": "Aucune progression disponible.",
        }

    @classmethod
    def terminer(cls, identifiant, *, operation="", message="Traitement terminé."):
        return cls.definir(identifiant, operation=operation, pourcentage=100, message=message)

    @classmethod
    def echouer(cls, identifiant, *, operation="", message="Traitement en échec."):
        return cls.definir(identifiant, operation=operation, pourcentage=100, message=message)

    @classmethod
    @contextmanager
    def verrou(cls, identifiant, operation):
        cle = cls.cle_verrou(identifiant, operation)
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


def _acteur_ou_none(acteur_id):
    """Retourne l'acteur qui déclenche une tâche, quand on veut tracer une décision."""

    if not acteur_id:
        return None

    User = get_user_model()
    queryset = User.objects.filter(id=acteur_id)
    if hasattr(User, "deleted_at"):
        queryset = queryset.filter(deleted_at__isnull=True)
    return queryset.first()


def _source_deja_centralisee(type_immerge, source):
    """Vérifie si une source métier possède déjà sa ligne centrale Immerge."""

    if type_immerge in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
        session_id = source.import_officiel.session_id
    elif type_immerge == Immerge.TypeImmerge.CONCOURS:
        session_id = source.import_officiel.session_id
    elif type_immerge == Immerge.TypeImmerge.SELECTIONNE:
        session_id = source.import_officiel.session_id
    elif type_immerge == Immerge.TypeImmerge.VOLONTAIRE:
        session_id = source.session_id
    else:
        raise ValidationError({"type_immerge": "Type d'immergé non pris en charge."})

    return ImmergeRepository.source_deja_centralisee(
        session_id=session_id,
        type_immerge=type_immerge,
        origine_id=source.id,
    )


def _centraliser_source(type_immerge, source_id):
    """Centralise une source précise vers la table Immerge."""

    if type_immerge in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
        source = ImmergeExamenRepository.get_by_id_pour_update(source_id)
        return ImmergeService.creer_depuis_examen(source)

    if type_immerge == Immerge.TypeImmerge.CONCOURS:
        source = ImmergeConcoursRepository.get_by_id_pour_update(source_id)
        return ImmergeService.creer_depuis_concours(source)

    if type_immerge == Immerge.TypeImmerge.SELECTIONNE:
        source = ImmergeSelectionneRepository.get_by_id_pour_update(source_id)
        return ImmergeService.creer_depuis_selectionne(source)

    if type_immerge == Immerge.TypeImmerge.VOLONTAIRE:
        source = InscriptionVolontaireRepository.get_by_id_pour_update(source_id)
        return ImmergeService.creer_depuis_volontaire(source)

    raise ValidationError({"type_immerge": "Type d'immergé non pris en charge."})


def _selectionner_sources_importees(type_immerge, *, import_officiel_id=None, session_id=None):
    """Retourne les sources importées valides à centraliser."""

    if type_immerge in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
        return ImmergeExamenRepository.lister_valides(
            import_officiel_id=import_officiel_id,
            session_id=session_id,
        ).filter(type_examen=type_immerge)

    if type_immerge == Immerge.TypeImmerge.CONCOURS:
        return ImmergeConcoursRepository.lister_valides(
            import_officiel_id=import_officiel_id,
            session_id=session_id,
        )

    if type_immerge == Immerge.TypeImmerge.SELECTIONNE:
        return ImmergeSelectionneRepository.lister_valides(
            import_officiel_id=import_officiel_id,
            session_id=session_id,
        )

    raise ValidationError({"type_immerge": "Type de source importée non pris en charge."})


@shared_task(bind=True, name="immerges.tasks.confirmer_import_vers_immerges_task")
def confirmer_import_vers_immerges_task(self, import_id, confirme_par_id=None):
    """Confirme un import officiel en créant les sources métier et les Immerge.

    Cette tâche existe côté immerges pour les traitements déclenchés depuis le
    module métier. L'action normale depuis l'écran d'import peut continuer à
    passer par imports_app.tasks.confirmer_import_task.
    """

    operation = "confirmation_import_vers_immerges"
    identifiant = f"import:{import_id}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {
                "ok": False,
                "import_id": import_id,
                "operation": operation,
                "message": "Confirmation déjà en cours pour cet import.",
            }

        try:
            ProgressionImmergeService.definir(
                identifiant,
                operation=operation,
                pourcentage=10,
                message="Confirmation de l'import vers les immergés...",
            )
            resultat = ImportVersImmergeService.confirmer_import(
                import_id,
                confirme_par=_acteur_ou_none(confirme_par_id),
            )
            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Import confirmé vers les immergés.",
            )
            return {
                "ok": True,
                "import_id": import_id,
                "lignes_traitees": resultat["lignes_traitees"],
                "lignes_importees": resultat["lignes_importees"],
                "lignes_erreur": resultat["lignes_erreur"],
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise


@shared_task(bind=True, name="immerges.tasks.centraliser_source_immerge_task")
def centraliser_source_immerge_task(self, type_immerge, source_id):
    """Crée la ligne centrale Immerge pour une source précise."""

    operation = "centralisation_source"
    identifiant = f"source:{type_immerge}:{source_id}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {
                "ok": False,
                "type_immerge": type_immerge,
                "source_id": source_id,
                "message": "Centralisation déjà en cours pour cette source.",
            }

        try:
            ProgressionImmergeService.definir(
                identifiant,
                operation=operation,
                pourcentage=30,
                message="Centralisation de la source...",
            )
            with transaction.atomic():
                immerge = _centraliser_source(type_immerge, source_id)

            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Source centralisée.",
            )
            return {
                "ok": True,
                "type_immerge": type_immerge,
                "source_id": source_id,
                "immerge_id": immerge.id,
                "code_fasoim": immerge.code_fasoim,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise


@shared_task(bind=True, name="immerges.tasks.centraliser_sources_importees_task")
def centraliser_sources_importees_task(self, type_immerge, import_officiel_id=None, session_id=None):
    """Centralise en lot des sources importées déjà validées.

    Sert surtout en reprise : si des sources existent déjà dans
    ImmergeExamen/ImmergeConcours/ImmergeSelectionne mais ne sont pas encore dans
    la table centrale Immerge.
    """

    operation = "centralisation_sources_importees"
    identifiant = f"sources:{type_immerge}:import:{import_officiel_id or 'tous'}:session:{session_id or 'toutes'}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {
                "ok": False,
                "type_immerge": type_immerge,
                "message": "Centralisation de sources déjà en cours.",
            }

        try:
            queryset = _selectionner_sources_importees(
                type_immerge,
                import_officiel_id=import_officiel_id,
                session_id=session_id,
            ).order_by("id")

            total = queryset.count()
            importees = 0
            ignorees = 0
            erreurs = 0

            if total == 0:
                ProgressionImmergeService.terminer(
                    identifiant,
                    operation=operation,
                    message="Aucune source importée à centraliser.",
                )
                return {
                    "ok": True,
                    "total": 0,
                    "importees": 0,
                    "ignorees": 0,
                    "erreurs": 0,
                }

            for index, source in enumerate(queryset.iterator(chunk_size=500), start=1):
                try:
                    if _source_deja_centralisee(type_immerge, source):
                        ignorees += 1
                    else:
                        _centraliser_source(type_immerge, source.id)
                        importees += 1
                except Exception:
                    erreurs += 1

                if index % 50 == 0 or index == total:
                    ProgressionImmergeService.definir(
                        identifiant,
                        operation=operation,
                        pourcentage=int(index * 100 / total),
                        message=f"Centralisation {index}/{total}...",
                    )

            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Centralisation des sources importées terminée.",
            )
            return {
                "ok": True,
                "total": total,
                "importees": importees,
                "ignorees": ignorees,
                "erreurs": erreurs,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise


@shared_task(bind=True, name="immerges.tasks.centraliser_volontaires_acceptes_task")
def centraliser_volontaires_acceptes_task(self, session_id=None):
    """Crée les Immerge centraux pour les volontaires acceptés non centralisés."""

    operation = "centralisation_volontaires_acceptes"
    identifiant = f"volontaires_acceptes:session:{session_id or 'toutes'}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {
                "ok": False,
                "message": "Centralisation des volontaires déjà en cours.",
            }

        try:
            queryset = InscriptionVolontaireRepository.lister_acceptees(session_id=session_id).order_by("id")
            total = queryset.count()
            importees = 0
            ignorees = 0
            erreurs = 0

            if total == 0:
                ProgressionImmergeService.terminer(
                    identifiant,
                    operation=operation,
                    message="Aucun volontaire accepté à centraliser.",
                )
                return {
                    "ok": True,
                    "total": 0,
                    "importees": 0,
                    "ignorees": 0,
                    "erreurs": 0,
                }

            for index, inscription in enumerate(queryset.iterator(chunk_size=500), start=1):
                try:
                    if _source_deja_centralisee(Immerge.TypeImmerge.VOLONTAIRE, inscription):
                        ignorees += 1
                    else:
                        ImmergeService.creer_depuis_volontaire(inscription)
                        importees += 1
                except Exception:
                    erreurs += 1

                if index % 50 == 0 or index == total:
                    ProgressionImmergeService.definir(
                        identifiant,
                        operation=operation,
                        pourcentage=int(index * 100 / total),
                        message=f"Centralisation volontaires {index}/{total}...",
                    )

            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Centralisation des volontaires acceptés terminée.",
            )
            return {
                "ok": True,
                "total": total,
                "importees": importees,
                "ignorees": ignorees,
                "erreurs": erreurs,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise


@shared_task(bind=True, name="immerges.tasks.accepter_volontaires_en_lot_task")
def accepter_volontaires_en_lot_task(self, inscription_ids, acteur_id=None, motif_decision="", creer_immerge=True):
    """Accepte plusieurs inscriptions volontaires et crée les Immerge si demandé."""

    operation = "acceptation_volontaires_lot"
    identifiant = f"acceptation_volontaires:{len(inscription_ids or [])}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {
                "ok": False,
                "message": "Acceptation en lot déjà en cours.",
            }

        acteur = _acteur_ou_none(acteur_id)
        inscription_ids = list(inscription_ids or [])
        total = len(inscription_ids)
        traitees = 0
        erreurs = 0

        try:
            if total == 0:
                ProgressionImmergeService.terminer(
                    identifiant,
                    operation=operation,
                    message="Aucune inscription volontaire fournie.",
                )
                return {"ok": True, "total": 0, "traitees": 0, "erreurs": 0}

            for index, inscription_id in enumerate(inscription_ids, start=1):
                try:
                    inscription = InscriptionVolontaireRepository.get_by_id_pour_update(inscription_id)
                    InscriptionVolontaireService.accepter(
                        inscription,
                        acteur=acteur,
                        motif_decision=motif_decision,
                        creer_immerge=creer_immerge,
                    )
                    traitees += 1
                except Exception:
                    erreurs += 1

                if index % 25 == 0 or index == total:
                    ProgressionImmergeService.definir(
                        identifiant,
                        operation=operation,
                        pourcentage=int(index * 100 / total),
                        message=f"Acceptation volontaires {index}/{total}...",
                    )

            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Acceptation en lot terminée.",
            )
            return {
                "ok": True,
                "total": total,
                "traitees": traitees,
                "erreurs": erreurs,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise


@shared_task(bind=True, name="immerges.tasks.generer_codes_fasoim_manquants_task")
def generer_codes_fasoim_manquants_task(self, session_id=None, type_immerge=None):
    """Génère les codes FasoIM pour les Immerge qui n'en ont pas encore."""

    operation = "generation_codes_manquants"
    identifiant = f"codes:session:{session_id or 'toutes'}:type:{type_immerge or 'tous'}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {"ok": False, "message": "Génération de codes déjà en cours."}

        try:
            queryset = ImmergeRepository.actifs().filter(code_fasoim="")
            if session_id is not None:
                queryset = queryset.filter(session_id=session_id)
            if type_immerge:
                queryset = queryset.filter(type_immerge=type_immerge)

            total = queryset.count()
            generes = 0
            erreurs = 0

            if total == 0:
                ProgressionImmergeService.terminer(
                    identifiant,
                    operation=operation,
                    message="Aucun code FasoIM manquant.",
                )
                return {"ok": True, "total": 0, "generes": 0, "erreurs": 0}

            for index, immerge in enumerate(queryset.order_by("id").iterator(chunk_size=500), start=1):
                try:
                    ImmergeService.generer_code_si_absent(immerge)
                    generes += 1
                except Exception:
                    erreurs += 1

                if index % 50 == 0 or index == total:
                    ProgressionImmergeService.definir(
                        identifiant,
                        operation=operation,
                        pourcentage=int(index * 100 / total),
                        message=f"Génération codes {index}/{total}...",
                    )

            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Génération des codes terminée.",
            )
            return {
                "ok": True,
                "total": total,
                "generes": generes,
                "erreurs": erreurs,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise


@shared_task(bind=True, name="immerges.tasks.regenerer_qr_codes_task")
def regenerer_qr_codes_task(self, session_id=None, type_immerge=None):
    """Régénère le contenu QR textuel à partir du code FasoIM existant."""

    operation = "regeneration_qr_codes"
    identifiant = f"qr:session:{session_id or 'toutes'}:type:{type_immerge or 'tous'}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {"ok": False, "message": "Régénération QR déjà en cours."}

        try:
            queryset = ImmergeRepository.actifs().exclude(code_fasoim="")
            if session_id is not None:
                queryset = queryset.filter(session_id=session_id)
            if type_immerge:
                queryset = queryset.filter(type_immerge=type_immerge)

            total = queryset.count()
            mis_a_jour = 0

            if total == 0:
                ProgressionImmergeService.terminer(
                    identifiant,
                    operation=operation,
                    message="Aucun QR à régénérer.",
                )
                return {"ok": True, "total": 0, "mis_a_jour": 0}

            for index, immerge in enumerate(queryset.order_by("id").iterator(chunk_size=500), start=1):
                qr_code = CodeFasoIMService.generer_qr_code(immerge.code_fasoim)
                if immerge.qr_code != qr_code:
                    immerge.qr_code = qr_code
                    immerge.save(update_fields=["qr_code", "updated_at"])
                    mis_a_jour += 1

                if index % 50 == 0 or index == total:
                    ProgressionImmergeService.definir(
                        identifiant,
                        operation=operation,
                        pourcentage=int(index * 100 / total),
                        message=f"Régénération QR {index}/{total}...",
                    )

            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Régénération des QR terminée.",
            )
            return {
                "ok": True,
                "total": total,
                "mis_a_jour": mis_a_jour,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise


@shared_task(bind=True, name="immerges.tasks.changer_statut_immerges_en_lot_task")
def changer_statut_immerges_en_lot_task(self, immerge_ids, statut):
    """Change le statut de plusieurs immergés en arrière-plan."""

    operation = "changement_statut_lot"
    identifiant = f"statut:{statut}:{len(immerge_ids or [])}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {"ok": False, "message": "Changement de statut déjà en cours."}

        if statut not in dict(Immerge.Statut.choices):
            raise ValidationError({"statut": "Statut d'immergé invalide."})

        immerge_ids = list(immerge_ids or [])
        total = len(immerge_ids)
        traitees = 0
        erreurs = 0

        try:
            if total == 0:
                ProgressionImmergeService.terminer(
                    identifiant,
                    operation=operation,
                    message="Aucun immergé fourni.",
                )
                return {"ok": True, "total": 0, "traitees": 0, "erreurs": 0}

            for index, immerge_id in enumerate(immerge_ids, start=1):
                try:
                    immerge = ImmergeRepository.get_by_id_pour_update(immerge_id)
                    ImmergeService.changer_statut(immerge, statut)
                    traitees += 1
                except Exception:
                    erreurs += 1

                if index % 50 == 0 or index == total:
                    ProgressionImmergeService.definir(
                        identifiant,
                        operation=operation,
                        pourcentage=int(index * 100 / total),
                        message=f"Changement statut {index}/{total}...",
                    )

            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Changement de statut terminé.",
            )
            return {
                "ok": True,
                "total": total,
                "traitees": traitees,
                "erreurs": erreurs,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise


@shared_task(bind=True, name="immerges.tasks.supprimer_immerge_logiquement_task")
def supprimer_immerge_logiquement_task(self, immerge_id):
    """Supprime logiquement un immergé central en brouillant code FasoIM et QR."""

    operation = "suppression_logique_immerge"
    identifiant = f"immerge:{immerge_id}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {"ok": False, "message": "Suppression déjà en cours pour cet immergé."}

        try:
            immerge = ImmergeRepository.get_by_id_pour_update(immerge_id)
            ImmergeService.supprimer_logiquement(immerge)
            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Immergé supprimé logiquement.",
            )
            return {"ok": True, "immerge_id": immerge_id}
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise


@shared_task(bind=True, name="immerges.tasks.supprimer_immerges_session_task")
def supprimer_immerges_session_task(self, session_id):
    """Supprime logiquement les immergés centraux d'une session.

    On passe par ImmergeService pour brouiller code_fasoim et qr_code.
    On évite donc une update SQL brute, même si elle serait plus rapide, parce
    que les champs uniques doivent rester réutilisables après suppression.
    """

    operation = "suppression_logique_session"
    identifiant = f"session:{session_id}"

    with ProgressionImmergeService.verrou(identifiant, operation) as verrou_acquis:
        if not verrou_acquis:
            return {"ok": False, "message": "Suppression de session déjà en cours."}

        try:
            queryset = ImmergeRepository.lister_par_session(session_id).order_by("id")
            total = queryset.count()
            supprimes = 0
            erreurs = 0

            if total == 0:
                ProgressionImmergeService.terminer(
                    identifiant,
                    operation=operation,
                    message="Aucun immergé à supprimer pour cette session.",
                )
                return {"ok": True, "total": 0, "supprimes": 0, "erreurs": 0}

            for index, immerge in enumerate(queryset.iterator(chunk_size=500), start=1):
                try:
                    ImmergeService.supprimer_logiquement(immerge)
                    supprimes += 1
                except Exception:
                    erreurs += 1

                if index % 50 == 0 or index == total:
                    ProgressionImmergeService.definir(
                        identifiant,
                        operation=operation,
                        pourcentage=int(index * 100 / total),
                        message=f"Suppression logique {index}/{total}...",
                    )

            ProgressionImmergeService.terminer(
                identifiant,
                operation=operation,
                message="Suppression logique des immergés de session terminée.",
            )
            return {
                "ok": True,
                "total": total,
                "supprimes": supprimes,
                "erreurs": erreurs,
            }
        except Exception as erreur:
            message = _message_exception(erreur)
            ProgressionImmergeService.echouer(identifiant, operation=operation, message=message)
            raise
