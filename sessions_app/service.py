from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ParametreSession, SessionImmersion


class SessionImmersionService:
    """Logique métier liée aux sessions d'immersion."""

    @staticmethod
    def _generer_code_brouille(objet_id, ancien_code):
        """
        Brouille un champ unique avant suppression logique.

        Objectif : conserver l'historique sans bloquer la recréation d'une session
        avec les mêmes données métier.
        """
        identifiant = objet_id or "X"
        suffixe = uuid4().hex[:8].upper()
        ancien = (ancien_code or "SESSION")[:20]
        return f"DEL-{identifiant}-{suffixe}-{ancien}"

    @staticmethod
    def verifier_session_non_supprimee(session):
        if session.deleted_at is not None:
            raise ValidationError("Cette session est supprimée logiquement.")

    @staticmethod
    def verifier_session_modifiable(session):
        SessionImmersionService.verifier_session_non_supprimee(session)

        if not session.est_modifiable:
            raise ValidationError(
                "Cette session n'est plus modifiable dans son statut actuel."
            )

    @staticmethod
    @transaction.atomic
    def creer_session_avec_parametres(session_data, parametres_data=None):
        """
        Crée une session et ses paramètres par défaut.

        Le code technique de session est généré par le modèle.
        Le code FasoIM des immergés sera généré plus tard dans le module immerges.
        """
        session_data = dict(session_data or {})
        parametres_data = dict(parametres_data or {})

        # Le code de session est généré par le système, pas saisi par l'utilisateur.
        session_data.pop("code", None)

        session = SessionImmersion(**session_data)
        session.save()

        parametres = ParametreSession(
            session=session,
            **parametres_data,
        )
        parametres.save()

        return session

    @staticmethod
    @transaction.atomic
    def modifier_session(session, session_data):
        SessionImmersionService.verifier_session_modifiable(session)

        session_data = dict(session_data or {})
        session_data.pop("code", None)
        session_data.pop("deleted_at", None)
        session_data.pop("created_at", None)
        session_data.pop("updated_at", None)

        for champ, valeur in session_data.items():
            setattr(session, champ, valeur)

        session.save()
        return session

    @staticmethod
    def changer_statut(session, nouveau_statut):
        SessionImmersionService.verifier_session_non_supprimee(session)

        statuts_valides = [choix[0] for choix in SessionImmersion.Statut.choices]
        if nouveau_statut not in statuts_valides:
            raise ValidationError("Statut de session invalide.")

        session.statut = nouveau_statut
        session.save(update_fields=["statut", "updated_at"])
        return session

    @staticmethod
    def ouvrir_session(session):
        return SessionImmersionService.changer_statut(
            session,
            SessionImmersion.Statut.OUVERTE,
        )

    @staticmethod
    def mettre_en_preparation(session):
        return SessionImmersionService.changer_statut(
            session,
            SessionImmersion.Statut.EN_PREPARATION,
        )

    @staticmethod
    def demarrer_session(session):
        return SessionImmersionService.changer_statut(
            session,
            SessionImmersion.Statut.EN_COURS,
        )

    @staticmethod
    def terminer_session(session):
        return SessionImmersionService.changer_statut(
            session,
            SessionImmersion.Statut.TERMINEE,
        )

    @staticmethod
    def archiver_session(session):
        return SessionImmersionService.changer_statut(
            session,
            SessionImmersion.Statut.ARCHIVEE,
        )

    @staticmethod
    @transaction.atomic
    def supprimer_logiquement(session):
        """
        Supprime logiquement une session.

        Règles :
        - pas de suppression physique ;
        - suppression logique en cascade des paramètres ;
        - brouillage du champ unique code ;
        - conservation de l'historique métier.
        """
        if session.deleted_at is not None:
            return session

        maintenant = timezone.now()

        parametres = getattr(session, "parametres", None)
        if parametres is not None:
            ParametreSessionService.supprimer_logiquement(
                parametres,
                date_suppression=maintenant,
            )

        ancien_code = session.code
        session.code = SessionImmersionService._generer_code_brouille(
            session.id,
            ancien_code,
        )
        session.statut = SessionImmersion.Statut.ANNULEE
        session.deleted_at = maintenant
        session.save(update_fields=["code", "statut", "deleted_at", "updated_at"])

        return session


class ParametreSessionService:
    """Logique métier liée aux paramètres de session."""

    @staticmethod
    def verifier_parametres_non_supprimes(parametres):
        if parametres.deleted_at is not None:
            raise ValidationError("Ces paramètres sont supprimés logiquement.")

        if parametres.session.deleted_at is not None:
            raise ValidationError("La session liée à ces paramètres est supprimée.")

    @staticmethod
    @transaction.atomic
    def modifier_parametres(parametres, parametres_data):
        ParametreSessionService.verifier_parametres_non_supprimes(parametres)
        SessionImmersionService.verifier_session_modifiable(parametres.session)

        parametres_data = dict(parametres_data or {})
        parametres_data.pop("session", None)
        parametres_data.pop("deleted_at", None)
        parametres_data.pop("created_at", None)
        parametres_data.pop("updated_at", None)

        for champ, valeur in parametres_data.items():
            setattr(parametres, champ, valeur)

        parametres.save()
        return parametres

    @staticmethod
    def import_autorise(session):
        if session.deleted_at is not None:
            return False

        parametres = getattr(session, "parametres", None)
        if parametres is None or parametres.deleted_at is not None:
            return False

        return parametres.utilise_import

    @staticmethod
    def inscription_volontaire_autorisee(session):
        if session.deleted_at is not None:
            return False

        parametres = getattr(session, "parametres", None)
        if parametres is None or parametres.deleted_at is not None:
            return False

        return parametres.utilise_inscription_volontaire

    @staticmethod
    def hebergement_autorise(session):
        parametres = getattr(session, "parametres", None)
        return bool(
            session.deleted_at is None
            and parametres is not None
            and parametres.deleted_at is None
            and parametres.hebergement_active
        )

    @staticmethod
    def repas_autorise(session):
        parametres = getattr(session, "parametres", None)
        return bool(
            session.deleted_at is None
            and parametres is not None
            and parametres.deleted_at is None
            and parametres.repas_active
        )

    @staticmethod
    def visite_medicale_autorisee(session):
        parametres = getattr(session, "parametres", None)
        return bool(
            session.deleted_at is None
            and parametres is not None
            and parametres.deleted_at is None
            and parametres.visite_medicale_active
        )

    @staticmethod
    def attestation_autorisee(session):
        parametres = getattr(session, "parametres", None)
        return bool(
            session.deleted_at is None
            and parametres is not None
            and parametres.deleted_at is None
            and parametres.attestation_active
        )

    @staticmethod
    def supprimer_logiquement(parametres, date_suppression=None):
        if parametres.deleted_at is not None:
            return parametres

        parametres.deleted_at = date_suppression or timezone.now()
        parametres.save(update_fields=["deleted_at", "updated_at"])
        return parametres
