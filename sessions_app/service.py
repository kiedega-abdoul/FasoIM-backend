from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ParametreSession, SessionImmersion


class VerificationClotureSessionService:
    """Orchestrateur global de clôture porté par sessions_app.

    Les modules restent responsables de leurs propres contrôles. Le service
    documents existant est utilisé comme vérificateur de compatibilité tant que
    les contrôles seront progressivement séparés par application.
    """

    @classmethod
    def verifier(cls, session):
        from documents.service import SessionClotureService as VerificateurModulesService

        return VerificateurModulesService.verifier(session)


class SessionImmersionService:
    TRANSITIONS_AUTORISEES = {
        SessionImmersion.Statut.BROUILLON: {
            SessionImmersion.Statut.OUVERTE,
            SessionImmersion.Statut.EN_PREPARATION,
            SessionImmersion.Statut.ANNULEE,
        },
        SessionImmersion.Statut.OUVERTE: {
            SessionImmersion.Statut.EN_PREPARATION,
            SessionImmersion.Statut.EN_COURS,
            SessionImmersion.Statut.ANNULEE,
        },
        SessionImmersion.Statut.EN_PREPARATION: {
            SessionImmersion.Statut.OUVERTE,
            SessionImmersion.Statut.EN_COURS,
            SessionImmersion.Statut.ANNULEE,
        },
        SessionImmersion.Statut.EN_COURS: {
            SessionImmersion.Statut.TERMINEE,
            SessionImmersion.Statut.ANNULEE,
        },
        SessionImmersion.Statut.TERMINEE: {SessionImmersion.Statut.ARCHIVEE},
        SessionImmersion.Statut.ARCHIVEE: set(),
        SessionImmersion.Statut.ANNULEE: set(),
    }
    CHAMPS_MODIFIABLES_EN_COURS = {"description"}

    @staticmethod
    def _generer_code_brouille(objet_id, ancien_code):
        identifiant = objet_id or "X"
        suffixe = uuid4().hex[:8].upper()
        ancien = (ancien_code or "SESSION")[:20]
        return f"DEL-{identifiant}-{suffixe}-{ancien}"

    @staticmethod
    def verifier_session_non_supprimee(session):
        if session.deleted_at is not None:
            raise ValidationError("Cette session est supprimée logiquement.")

    @staticmethod
    def verifier_session_modifiable(session, champs=None):
        SessionImmersionService.verifier_session_non_supprimee(session)
        if session.statut in {
            SessionImmersion.Statut.TERMINEE,
            SessionImmersion.Statut.ARCHIVEE,
            SessionImmersion.Statut.ANNULEE,
        }:
            raise ValidationError("Cette session n'est plus modifiable dans son statut actuel.")
        if session.statut == SessionImmersion.Statut.EN_COURS:
            champs_interdits = set(champs or ()) - SessionImmersionService.CHAMPS_MODIFIABLES_EN_COURS
            if champs_interdits:
                raise ValidationError({
                    "session": "Pendant une session en cours, seule la description peut être modifiée.",
                    "champs_interdits": sorted(champs_interdits),
                })

    @staticmethod
    @transaction.atomic
    def creer_session(session_data):
        session_data = dict(session_data or {})
        session_data.pop("code", None)
        session_data.pop("numero_promotion", None)
        session = SessionImmersion(**session_data)
        session.save()
        return session

    @staticmethod
    @transaction.atomic
    def creer_session_avec_parametres(session_data, parametres_data=None):
        """Compatibilité interne : crée la session puis ses paramètres."""
        session = SessionImmersionService.creer_session(session_data)
        ParametreSessionService.configurer_parametres(
            session,
            dict(parametres_data or {}),
        )
        return session

    @staticmethod
    @transaction.atomic
    def modifier_session(session, session_data):
        session_data = dict(session_data or {})
        for champ in {"code", "numero_promotion", "statut", "motif_annulation", "date_annulation", "deleted_at", "created_at", "updated_at"}:
            session_data.pop(champ, None)
        SessionImmersionService.verifier_session_modifiable(session, session_data.keys())
        for champ, valeur in session_data.items():
            setattr(session, champ, valeur)
        session.save()
        return session

    @classmethod
    def verifier_unicite_session_active(cls, session, nouveau_statut):
        statuts_actifs = {
            SessionImmersion.Statut.OUVERTE,
            SessionImmersion.Statut.EN_PREPARATION,
            SessionImmersion.Statut.EN_COURS,
        }
        if nouveau_statut not in statuts_actifs:
            return

        concurrentes = SessionImmersion.objects.filter(
            deleted_at__isnull=True,
            type_session=session.type_session,
            statut__in=statuts_actifs,
        ).exclude(pk=session.pk)
        if concurrentes.exists():
            raise ValidationError({
                "statut": (
                    "Une autre session active existe déjà pour ce type de session. "
                    "Terminez, archivez ou annulez-la avant d'activer celle-ci."
                )
            })

        # Une session VOLONTAIRE ou MIXTE ouverte aux inscriptions partage le
        # même formulaire public. Il ne peut donc y en avoir qu'une à la fois.
        if nouveau_statut == SessionImmersion.Statut.OUVERTE and session.type_session in {
            SessionImmersion.TypeSession.VOLONTAIRE,
            SessionImmersion.TypeSession.MIXTE,
        }:
            autre_session_volontaire = SessionImmersion.objects.filter(
                deleted_at__isnull=True,
                statut=SessionImmersion.Statut.OUVERTE,
                type_session__in=[
                    SessionImmersion.TypeSession.VOLONTAIRE,
                    SessionImmersion.TypeSession.MIXTE,
                ],
                parametres__mode_entree__in=[
                    ParametreSession.ModeEntree.INSCRIPTION,
                    ParametreSession.ModeEntree.MIXTE,
                ],
                parametres__deleted_at__isnull=True,
            ).exclude(pk=session.pk)
            if autre_session_volontaire.exists():
                raise ValidationError({
                    "statut": (
                        "Une session acceptant déjà les demandes volontaires est ouverte. "
                        "Fermez-la avant d'en ouvrir une autre."
                    )
                })

    @classmethod
    def changer_statut(cls, session, nouveau_statut):
        cls.verifier_session_non_supprimee(session)
        if nouveau_statut == session.statut:
            return session
        autorises = cls.TRANSITIONS_AUTORISEES.get(session.statut, set())
        if nouveau_statut not in autorises:
            raise ValidationError({
                "statut": f"Transition interdite : {session.statut} vers {nouveau_statut}."
            })
        if nouveau_statut in {
            SessionImmersion.Statut.EN_PREPARATION,
            SessionImmersion.Statut.OUVERTE,
            SessionImmersion.Statut.EN_COURS,
        } and not ParametreSession.objects.filter(
            session=session,
            deleted_at__isnull=True,
        ).exists():
            raise ValidationError({
                "parametres": "Configurez les paramètres de la session avant de changer son statut."
            })

        cls.verifier_unicite_session_active(session, nouveau_statut)

        if nouveau_statut == SessionImmersion.Statut.TERMINEE:
            etat = VerificationClotureSessionService.verifier(session)
            if not etat.cloturable:
                raise ValidationError({
                    "session": "La session ne peut pas être terminée tant que des opérations restent ouvertes.",
                    "blocages": etat.blocages,
                })
        session.statut = nouveau_statut
        session.save(update_fields=["statut", "updated_at"])
        return session

    @classmethod
    def ouvrir_session(cls, session):
        return cls.changer_statut(session, SessionImmersion.Statut.OUVERTE)

    @classmethod
    def mettre_en_preparation(cls, session):
        return cls.changer_statut(session, SessionImmersion.Statut.EN_PREPARATION)

    @classmethod
    def demarrer_session(cls, session):
        return cls.changer_statut(session, SessionImmersion.Statut.EN_COURS)

    @classmethod
    def terminer_session(cls, session):
        return cls.changer_statut(session, SessionImmersion.Statut.TERMINEE)

    @classmethod
    def archiver_session(cls, session):
        return cls.changer_statut(session, SessionImmersion.Statut.ARCHIVEE)

    @classmethod
    @transaction.atomic
    def annuler_session(cls, session, motif):
        motif = (motif or "").strip()
        if not motif:
            raise ValidationError({"motif": "Le motif d'annulation est obligatoire."})
        cls.changer_statut(session, SessionImmersion.Statut.ANNULEE)
        session.motif_annulation = motif
        session.date_annulation = timezone.now()
        session.save(update_fields=["motif_annulation", "date_annulation", "updated_at"])
        return session

    @classmethod
    @transaction.atomic
    def supprimer_logiquement(cls, session):
        if session.deleted_at is not None:
            return session
        if session.statut != SessionImmersion.Statut.BROUILLON:
            raise ValidationError(
                "Seule une session encore en brouillon peut être supprimée logiquement. "
                "Pour une session planifiée ou démarrée, utilisez l'annulation métier."
            )
        maintenant = timezone.now()
        parametres = getattr(session, "parametres", None)
        if parametres is not None:
            ParametreSessionService.supprimer_logiquement(parametres, maintenant)
        session.code = cls._generer_code_brouille(session.id, session.code)
        session.deleted_at = maintenant
        session.save(update_fields=["code", "deleted_at", "updated_at"])
        return session


class ParametreSessionService:
    CHAMPS_TEXTUELS_EN_COURS = {"directives_generales", "consignes_generales"}

    @staticmethod
    def verifier_parametres_non_supprimes(parametres):
        if parametres.deleted_at is not None:
            raise ValidationError("Ces paramètres sont supprimés logiquement.")
        if parametres.session.deleted_at is not None:
            raise ValidationError("La session liée à ces paramètres est supprimée.")

    @classmethod
    @transaction.atomic
    def configurer_parametres(cls, session, parametres_data):
        SessionImmersionService.verifier_session_non_supprimee(session)
        if session.statut != SessionImmersion.Statut.BROUILLON:
            raise ValidationError(
                "Les paramètres initiaux doivent être configurés pendant que la session est en brouillon."
            )
        if ParametreSession.objects.filter(session=session, deleted_at__isnull=True).exists():
            raise ValidationError("Les paramètres de cette session sont déjà configurés.")
        parametres = ParametreSession(session=session, **dict(parametres_data or {}))
        parametres.save()
        return parametres

    @classmethod
    @transaction.atomic
    def modifier_parametres(cls, parametres, parametres_data):
        cls.verifier_parametres_non_supprimes(parametres)
        donnees = dict(parametres_data or {})
        for champ in {"session", "deleted_at", "created_at", "updated_at"}:
            donnees.pop(champ, None)
        session = parametres.session
        SessionImmersionService.verifier_session_modifiable(session)
        if session.statut == SessionImmersion.Statut.EN_COURS:
            interdits = set(donnees) - cls.CHAMPS_TEXTUELS_EN_COURS
            if interdits:
                raise ValidationError({
                    "parametres": "Pendant la session, seules les directives et les consignes peuvent être corrigées.",
                    "champs_interdits": sorted(interdits),
                })
        for champ, valeur in donnees.items():
            setattr(parametres, champ, valeur)
        parametres.save()
        return parametres

    @staticmethod
    def _module_actif(session, champ):
        parametres = getattr(session, "parametres", None)
        return bool(session.deleted_at is None and parametres and parametres.deleted_at is None and getattr(parametres, champ))

    @staticmethod
    def import_autorise(session):
        parametres = getattr(session, "parametres", None)
        return bool(session.deleted_at is None and parametres and parametres.deleted_at is None and parametres.utilise_import)

    @staticmethod
    def inscription_volontaire_autorisee(session):
        parametres = getattr(session, "parametres", None)
        return bool(session.deleted_at is None and parametres and parametres.deleted_at is None and parametres.utilise_inscription_volontaire)

    @classmethod
    def hebergement_autorise(cls, session): return cls._module_actif(session, "hebergement_active")
    @classmethod
    def repas_autorise(cls, session): return cls._module_actif(session, "repas_active")
    @classmethod
    def visite_medicale_autorisee(cls, session): return cls._module_actif(session, "visite_medicale_active")
    @classmethod
    def attestation_autorisee(cls, session): return cls._module_actif(session, "attestation_active")
    @classmethod
    def activites_autorisees(cls, session): return cls._module_actif(session, "activites_active")
    @classmethod
    def evaluations_autorisees(cls, session): return cls._module_actif(session, "evaluation_active")
    @classmethod
    def consultation_publique_autorisee(cls, session): return cls._module_actif(session, "consultation_publique_active")

    @staticmethod
    def supprimer_logiquement(parametres, date_suppression=None):
        if parametres.deleted_at is not None:
            return parametres
        parametres.deleted_at = date_suppression or timezone.now()
        parametres.save(update_fields=["deleted_at", "updated_at"])
        return parametres
