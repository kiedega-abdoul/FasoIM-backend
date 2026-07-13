from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Iterable

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.defaultfilters import linebreaksbr
from django.utils import timezone
from django.utils.html import strip_tags

from audit.models import JournalAction
from audit.service import JournalActionService

from .repository import ContactEmail, NotificationRepository


logger = logging.getLogger(__name__)


class ErreurEnvoiEmail(Exception):
    """Erreur temporaire ou SMTP autorisant une nouvelle tentative Celery."""


@dataclass(frozen=True)
class ResultatEnvoi:
    envoye: bool
    statut: str
    cle_deduplication: str
    destinataire_masque: str = ""
    motif: str = ""
    journal_id: int | None = None

    def as_dict(self):
        return asdict(self)


class TypesMessage:
    BIENVENUE_ACTEUR = "BIENVENUE_ACTEUR"
    REINITIALISATION_MOT_DE_PASSE = "REINITIALISATION_MOT_DE_PASSE"
    CHANGEMENT_MOT_DE_PASSE = "CHANGEMENT_MOT_DE_PASSE"
    STATUT_COMPTE_ACTEUR = "STATUT_COMPTE_ACTEUR"
    AFFECTATION_ACTEUR = "AFFECTATION_ACTEUR"
    ROLE_ACTEUR = "ROLE_ACTEUR"
    PERMISSION_ACTEUR = "PERMISSION_ACTEUR"
    DELEGATION_ACTEUR = "DELEGATION_ACTEUR"
    SESSION_MODIFIEE = "SESSION_MODIFIEE"
    IMPORT_TERMINE = "IMPORT_TERMINE"
    IMPORT_ECHOUE = "IMPORT_ECHOUE"
    DECISION_VOLONTAIRE = "DECISION_VOLONTAIRE"
    AFFECTATION_IMMERGE_PUBLIEE = "AFFECTATION_IMMERGE_PUBLIEE"
    AFFECTATION_IMMERGE_CORRIGEE = "AFFECTATION_IMMERGE_CORRIGEE"
    ORGANISATION_PRETE = "ORGANISATION_PRETE"
    PUBLICATION_VALIDEE = "PUBLICATION_VALIDEE"
    PUBLICATION_A_CORRIGER = "PUBLICATION_A_CORRIGER"
    ORGANISATION_REFUSEE = "ORGANISATION_REFUSEE"
    ACTIVITE_ATTRIBUEE = "ACTIVITE_ATTRIBUEE"
    TRAITEMENT_TERMINE = "TRAITEMENT_TERMINE"
    TRAITEMENT_ECHOUE = "TRAITEMENT_ECHOUE"
    INCIDENT_IMPORTANT = "INCIDENT_IMPORTANT"
    RAPPORT_DISPONIBLE = "RAPPORT_DISPONIBLE"
    RAPPORT_ECHOUE = "RAPPORT_ECHOUE"
    DOCUMENT_A_SIGNER = "DOCUMENT_A_SIGNER"
    DOCUMENT_SIGNE = "DOCUMENT_SIGNE"
    ATTESTATIONS_SOUMISES_DGAS = "ATTESTATIONS_SOUMISES_DGAS"
    CENTRE_PRET_ATTESTATIONS = "CENTRE_PRET_ATTESTATIONS"
    ATTESTATIONS_REFUSEES = "ATTESTATIONS_REFUSEES"
    ATTESTATION_PUBLIEE = "ATTESTATION_PUBLIEE"
    ATTESTATION_REMPLACEE = "ATTESTATION_REMPLACEE"
    RELAIS_ETABLISSEMENT = "RELAIS_ETABLISSEMENT"
    EMAIL_TEST = "EMAIL_TEST"


class NotificationService:
    """Envoie des e-mails sans créer de table dans notifications.

    L'idempotence repose sur un verrou Redis et sur les succès immuables du
    journal d'audit. Un même événement ne peut donc pas être envoyé deux fois au
    même destinataire. Un échec, lui, n'interdit pas une nouvelle tentative.
    """

    CODE_ACTION = "envoyer_email"
    STATUT_ENVOYE = "ENVOYE"
    STATUT_DEJA_ENVOYE = "DEJA_ENVOYE"
    STATUT_EN_COURS = "EN_COURS"
    STATUT_REFUSE = "REFUSE"
    STATUT_ECHEC = "ECHEC"

    @staticmethod
    def masquer_email(email):
        email = str(email or "").strip().lower()
        if "@" not in email:
            return "[INVALIDE]"
        local, domaine = email.split("@", 1)
        visible = local[:1] if local else "*"
        return f"{visible}***@{domaine}"

    @staticmethod
    def empreinte_email(email):
        return hashlib.sha256(str(email or "").strip().lower().encode("utf-8")).hexdigest()

    @staticmethod
    def normaliser_cle(valeur):
        texte = re.sub(r"\s+", "_", str(valeur or "").strip().upper())
        texte = re.sub(r"[^A-Z0-9:_\-.]", "", texte)
        return texte[:220]

    @classmethod
    def construire_cle(
        cls,
        *,
        destinataire,
        type_message,
        cle_evenement="",
        objet_type="",
        objet_id=None,
        version="",
        sujet="",
        message="",
    ):
        base_evenement = cls.normaliser_cle(cle_evenement)
        if not base_evenement:
            contenu = "|".join(
                [
                    str(type_message or "EMAIL"),
                    str(objet_type or ""),
                    str(objet_id or ""),
                    str(version or ""),
                    str(sujet or ""),
                    str(message or ""),
                ]
            )
            base_evenement = hashlib.sha256(contenu.encode("utf-8")).hexdigest()
        email_hash = cls.empreinte_email(destinataire)[:24]
        cle = f"{cls.normaliser_cle(type_message or 'EMAIL')}:{base_evenement}:{email_hash}"
        if len(cle) <= 255:
            return cle
        digest = hashlib.sha256(cle.encode("utf-8")).hexdigest()
        return f"{cle[:180]}:{digest}"

    @staticmethod
    def _contexte_audit(
        *,
        type_message,
        cle_deduplication,
        destinataire,
        contexte=None,
        tentative=None,
    ):
        valeur = {
            "type_message": str(type_message or "EMAIL")[:100],
            "cle_deduplication": cle_deduplication,
            "destinataire_masque": NotificationService.masquer_email(destinataire),
            "empreinte_destinataire": NotificationService.empreinte_email(destinataire),
        }
        if tentative is not None:
            valeur["tentative"] = tentative
        valeur.update(contexte or {})
        return valeur

    @staticmethod
    def _acquerir_verrou(cle_deduplication):
        timeout = int(getattr(settings, "NOTIFICATIONS_LOCK_SECONDS", 300))
        jeton = uuid.uuid4().hex
        cle_cache = f"notifications:lock:{hashlib.sha256(cle_deduplication.encode()).hexdigest()}"
        try:
            acquis = cache.add(cle_cache, jeton, timeout=max(30, timeout))
        except Exception as exc:
            logger.exception("Redis indisponible pour le verrou de notification")
            raise ErreurEnvoiEmail("VERROU_REDIS_INDISPONIBLE") from exc
        return cle_cache, jeton, bool(acquis)

    @staticmethod
    def _liberer_verrou(cle_cache, jeton):
        try:
            courant = cache.get(cle_cache)
            if courant == jeton:
                cache.delete(cle_cache)
        except Exception:
            logger.exception("Impossible de libérer le verrou de notification %s", cle_cache)

    @staticmethod
    def _cle_succes_cache(cle_deduplication):
        digest = hashlib.sha256(cle_deduplication.encode("utf-8")).hexdigest()
        return f"notifications:succes:{digest}"

    @classmethod
    def _succes_cache_existe(cls, cle_deduplication):
        try:
            return bool(cache.get(cls._cle_succes_cache(cle_deduplication)))
        except Exception:
            return False

    @classmethod
    def _memoriser_succes_cache(cls, cle_deduplication):
        timeout = int(getattr(settings, "NOTIFICATIONS_DEDUP_SUCCESS_SECONDS", 31536000))
        try:
            cache.set(
                cls._cle_succes_cache(cle_deduplication),
                True,
                timeout=max(3600, timeout),
            )
        except Exception:
            logger.exception("Impossible de mémoriser le succès Redis de %s", cle_deduplication)

    @classmethod
    def envoyer_email(
        cls,
        *,
        destinataire,
        sujet,
        message,
        type_message,
        cle_evenement="",
        nom_destinataire="",
        html_message="",
        acteur=None,
        immerge=None,
        session=None,
        region=None,
        centre=None,
        objet=None,
        objet_type="",
        objet_id=None,
        objet_reference="",
        version="",
        contexte=None,
        task_id="",
        tentative=1,
        forcer=False,
    ) -> ResultatEnvoi:
        email = NotificationRepository.email_valide(destinataire)
        cle = cls.construire_cle(
            destinataire=destinataire,
            type_message=type_message,
            cle_evenement=cle_evenement,
            objet_type=objet_type,
            objet_id=objet_id,
            version=version,
            sujet=sujet,
            message=message,
        )
        contexte_audit = cls._contexte_audit(
            type_message=type_message,
            cle_deduplication=cle,
            destinataire=destinataire,
            contexte=contexte,
            tentative=tentative,
        )

        if not email:
            journal = JournalActionService.journaliser_refus(
                code_action=cls.CODE_ACTION,
                module_source="notifications",
                origine=JournalAction.Origine.CELERY if task_id else JournalAction.Origine.SYSTEME,
                canal=JournalAction.Canal.EMAIL,
                acteur=acteur,
                immerge=immerge,
                session=session,
                region=region,
                centre=centre,
                objet=objet,
                objet_type=objet_type,
                objet_id=objet_id,
                objet_reference=objet_reference,
                motif="ADRESSE_EMAIL_ABSENTE_OU_INVALIDE",
                contexte=contexte_audit,
                task_id=task_id,
            )
            return ResultatEnvoi(
                envoye=False,
                statut=cls.STATUT_REFUSE,
                cle_deduplication=cle,
                destinataire_masque=cls.masquer_email(destinataire),
                motif="ADRESSE_EMAIL_ABSENTE_OU_INVALIDE",
                journal_id=getattr(journal, "id", None),
            )

        cle_cache = jeton = None
        try:
            cle_cache, jeton, acquis = cls._acquerir_verrou(cle)
            if not acquis:
                return ResultatEnvoi(
                    envoye=False,
                    statut=cls.STATUT_EN_COURS,
                    cle_deduplication=cle,
                    destinataire_masque=cls.masquer_email(email),
                    motif="UN_ENVOI_IDENTIQUE_EST_DEJA_EN_COURS",
                )

            if not forcer:
                succes = NotificationRepository.journal_succes(cle)
                succes_cache = cls._succes_cache_existe(cle)
                if succes or succes_cache:
                    return ResultatEnvoi(
                        envoye=False,
                        statut=cls.STATUT_DEJA_ENVOYE,
                        cle_deduplication=cle,
                        destinataire_masque=cls.masquer_email(email),
                        motif=(
                            "EMAIL_IDENTIQUE_DEJA_ENVOYE_AVEC_SUCCES"
                            if succes
                            else "EMAIL_IDENTIQUE_DEJA_ENVOYE_SUCCES_REDIS"
                        ),
                        journal_id=getattr(succes, "id", None),
                    )

                ttl_tentative = int(getattr(settings, "NOTIFICATIONS_TENTATIVE_TTL_SECONDS", 600))
                depuis = timezone.now() - timedelta(seconds=max(30, ttl_tentative))
                tentative_recente = NotificationRepository.tentative_recente(cle, depuis)
                dernier_echec = NotificationRepository.dernier_echec(cle)
                tentative_non_terminee = bool(
                    tentative_recente
                    and (
                        dernier_echec is None
                        or dernier_echec.created_at < tentative_recente.created_at
                    )
                )
                if tentative_non_terminee:
                    return ResultatEnvoi(
                        envoye=False,
                        statut=cls.STATUT_EN_COURS,
                        cle_deduplication=cle,
                        destinataire_masque=cls.masquer_email(email),
                        motif="TENTATIVE_IDENTIQUE_RECENTE",
                        journal_id=tentative_recente.id,
                    )

            JournalActionService.journaliser_tentative(
                code_action=cls.CODE_ACTION,
                module_source="notifications",
                origine=JournalAction.Origine.CELERY if task_id else JournalAction.Origine.SYSTEME,
                canal=JournalAction.Canal.EMAIL,
                acteur=acteur,
                immerge=immerge,
                session=session,
                region=region,
                centre=centre,
                objet=objet,
                objet_type=objet_type,
                objet_id=objet_id,
                objet_reference=objet_reference,
                motif="Tentative d'envoi d'un e-mail FasoIM.",
                contexte=contexte_audit,
                task_id=task_id,
                strict=True,
            )

            texte = strip_tags(str(message or "")).strip()
            html = str(html_message or "").strip() or str(linebreaksbr(texte))
            email_message = EmailMultiAlternatives(
                subject=str(sujet or "FasoIM")[:255],
                body=texte,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                to=[email],
            )
            email_message.attach_alternative(html, "text/html")
            debut = time.monotonic()
            nombre_envoye = email_message.send(fail_silently=False)
            duree_ms = int((time.monotonic() - debut) * 1000)
            if not nombre_envoye:
                raise ErreurEnvoiEmail("LE_BACKEND_EMAIL_N_A_CONFIRME_AUCUN_ENVOI")

            # Le marqueur Redis est posé immédiatement après l'acceptation SMTP.
            # Il évite un doublon même si PostgreSQL devient indisponible pendant
            # la journalisation du succès.
            cls._memoriser_succes_cache(cle)
            journal = None
            motif_resultat = ""
            try:
                journal = JournalActionService.journaliser_succes(
                    code_action=cls.CODE_ACTION,
                    module_source="notifications",
                    origine=JournalAction.Origine.CELERY if task_id else JournalAction.Origine.SYSTEME,
                    canal=JournalAction.Canal.EMAIL,
                    acteur=acteur,
                    immerge=immerge,
                    session=session,
                    region=region,
                    centre=centre,
                    objet=objet,
                    objet_type=objet_type,
                    objet_id=objet_id,
                    objet_reference=objet_reference,
                    motif="E-mail accepté par le backend d'envoi.",
                    contexte=contexte_audit,
                    task_id=task_id,
                    duree_ms=duree_ms,
                    strict=True,
                )
            except Exception:
                # L'e-mail a déjà été accepté. On ne relance surtout pas : le
                # marqueur Redis protège contre le doublon et l'erreur est loguée.
                logger.exception(
                    "E-mail envoyé mais succès non journalisé pour %s",
                    cle,
                )
                motif_resultat = "EMAIL_ENVOYE_MAIS_AUDIT_INDISPONIBLE"
            return ResultatEnvoi(
                envoye=True,
                statut=cls.STATUT_ENVOYE,
                cle_deduplication=cle,
                destinataire_masque=cls.masquer_email(email),
                motif=motif_resultat,
                journal_id=getattr(journal, "id", None),
            )
        except ErreurEnvoiEmail as exc:
            JournalActionService.journaliser_echec(
                code_action=cls.CODE_ACTION,
                module_source="notifications",
                origine=JournalAction.Origine.CELERY if task_id else JournalAction.Origine.SYSTEME,
                canal=JournalAction.Canal.EMAIL,
                acteur=acteur,
                immerge=immerge,
                session=session,
                region=region,
                centre=centre,
                objet=objet,
                objet_type=objet_type,
                objet_id=objet_id,
                objet_reference=objet_reference,
                motif=str(exc)[:1000],
                contexte=contexte_audit,
                task_id=task_id,
            )
            raise
        except Exception as exc:
            JournalActionService.journaliser_echec(
                code_action=cls.CODE_ACTION,
                module_source="notifications",
                origine=JournalAction.Origine.CELERY if task_id else JournalAction.Origine.SYSTEME,
                canal=JournalAction.Canal.EMAIL,
                acteur=acteur,
                immerge=immerge,
                session=session,
                region=region,
                centre=centre,
                objet=objet,
                objet_type=objet_type,
                objet_id=objet_id,
                objet_reference=objet_reference,
                motif=f"{exc.__class__.__name__}: {str(exc)[:800]}",
                contexte=contexte_audit,
                task_id=task_id,
            )
            raise ErreurEnvoiEmail(str(exc)) from exc
        finally:
            if cle_cache and jeton:
                cls._liberer_verrou(cle_cache, jeton)

    @classmethod
    def planifier_email_apres_commit(cls, **payload):
        def _planifier():
            try:
                from .tasks import envoyer_email_task

                envoyer_email_task.delay(payload)
            except Exception:
                logger.exception("Impossible de planifier l'e-mail %s", payload.get("type_message"))

        transaction.on_commit(_planifier)

    @classmethod
    def planifier_email_acteur(
        cls,
        *,
        acteur,
        sujet,
        message,
        type_message,
        cle_evenement,
        session=None,
        region=None,
        centre=None,
        objet=None,
        contexte=None,
    ):
        contact = NotificationRepository.contact_acteur(acteur)
        if not contact:
            JournalActionService.journaliser_refus(
                code_action=cls.CODE_ACTION,
                module_source="notifications",
                origine=JournalAction.Origine.SYSTEME,
                canal=JournalAction.Canal.EMAIL,
                acteur=acteur,
                session=session,
                region=region,
                centre=centre,
                objet=objet,
                motif="ACTEUR_SANS_EMAIL_VALIDE",
                contexte={
                    "type_message": type_message,
                    "cle_evenement": cle_evenement,
                    "acteur_id": getattr(acteur, "id", None),
                },
            )
            return False
        cls.planifier_email_apres_commit(
            destinataire=contact.email,
            nom_destinataire=contact.nom,
            sujet=sujet,
            message=message,
            type_message=type_message,
            cle_evenement=cle_evenement,
            acteur_id=contact.acteur_id,
            session_id=getattr(session, "id", session),
            region_id=getattr(region, "id", region),
            centre_id=getattr(centre, "id", centre),
            objet_type=objet.__class__.__name__ if objet is not None else "",
            objet_id=getattr(objet, "id", None),
            objet_reference=str(getattr(objet, "code", "") or ""),
            contexte=contexte or {},
        )
        return True

    @classmethod
    def planifier_email_immerge(
        cls,
        *,
        immerge,
        sujet,
        message,
        type_message,
        cle_evenement,
        region=None,
        centre=None,
        objet=None,
        contexte=None,
    ):
        contact = NotificationRepository.contact_immerge(immerge)
        if contact:
            cls.planifier_email_apres_commit(
                destinataire=contact.email,
                nom_destinataire=contact.nom,
                sujet=sujet,
                message=message,
                type_message=type_message,
                cle_evenement=cle_evenement,
                immerge_id=immerge.id,
                session_id=immerge.session_id,
                region_id=getattr(region, "id", region),
                centre_id=getattr(centre, "id", centre),
                objet_type=objet.__class__.__name__ if objet is not None else "",
                objet_id=getattr(objet, "id", None),
                objet_reference=str(getattr(objet, "code", "") or ""),
                contexte=contexte or {},
            )
            return {"direct": True, "relais": 0}
        return {"direct": False, "relais": 0}

    @classmethod
    def planifier_information_immerges(
        cls,
        *,
        immerge_ids,
        type_message,
        sujet,
        message,
        cle_evenement,
        url_portail="",
        contexte=None,
        region_id=None,
        centre_id=None,
    ):
        """Point d'intégration pour publications d'affectations/attestations."""
        ids = list(dict.fromkeys(int(i) for i in (immerge_ids or [])))

        def _planifier():
            try:
                from .tasks import informer_immerges_task

                informer_immerges_task.delay(
                    ids,
                    type_message=type_message,
                    sujet=sujet,
                    message=message,
                    cle_evenement=cle_evenement,
                    url_portail=url_portail,
                    contexte_global=contexte or {},
                    region_id=region_id,
                    centre_id=centre_id,
                )
            except Exception:
                logger.exception("Impossible de planifier l'information de %s immergés", len(ids))

        transaction.on_commit(_planifier)

    @classmethod
    def planifier_acteurs_role(
        cls,
        *,
        code_role,
        sujet,
        message,
        type_message,
        cle_evenement,
        session_id=None,
        region_code=None,
        centre_id=None,
        contexte=None,
    ):
        def _planifier():
            try:
                from .tasks import notifier_acteurs_role_task

                notifier_acteurs_role_task.delay(
                    code_role,
                    sujet=sujet,
                    message=message,
                    type_message=type_message,
                    cle_evenement=cle_evenement,
                    session_id=session_id,
                    region_code=region_code,
                    centre_id=centre_id,
                    contexte=contexte or {},
                )
            except Exception:
                logger.exception("Impossible de planifier l'information du rôle %s", code_role)

        transaction.on_commit(_planifier)

    @classmethod
    def planifier_affectations_publiees(
        cls,
        *,
        immerge_ids,
        publication_reference,
        url_portail="",
        region_id=None,
        centre_id=None,
    ):
        url = url_portail or getattr(settings, "FASOIM_PUBLIC_URL", "http://127.0.0.1:3000")
        cls.planifier_information_immerges(
            immerge_ids=immerge_ids,
            type_message=TypesMessage.AFFECTATION_IMMERGE_PUBLIEE,
            sujet="Vos informations d'affectation FasoIM sont disponibles",
            message=(
                "Vos informations d'affectation FasoIM sont disponibles. "
                f"Consultez votre fiche officielle sur la plateforme : {url}"
            ),
            cle_evenement=f"AFFECTATIONS_PUBLIEES:{publication_reference}",
            url_portail=url,
            region_id=region_id,
            centre_id=centre_id,
            contexte={"publication_reference": str(publication_reference)},
        )

    @classmethod
    def planifier_attestations_publiees(
        cls,
        *,
        immerge_ids,
        publication_reference,
        url_portail="",
        region_id=None,
        centre_id=None,
    ):
        url = url_portail or getattr(settings, "FASOIM_PUBLIC_URL", "http://127.0.0.1:3000")
        cls.planifier_information_immerges(
            immerge_ids=immerge_ids,
            type_message=TypesMessage.ATTESTATION_PUBLIEE,
            sujet="Votre attestation FasoIM est disponible",
            message=(
                "Votre attestation FasoIM est disponible. "
                f"Consultez ou téléchargez le document officiel sur : {url}"
            ),
            cle_evenement=f"ATTESTATIONS_PUBLIEES:{publication_reference}",
            url_portail=url,
            region_id=region_id,
            centre_id=centre_id,
            contexte={"publication_reference": str(publication_reference)},
        )

    @classmethod
    def planifier_rapport_disponible(
        cls,
        *,
        acteur,
        rapport_reference,
        type_rapport,
        url_telechargement,
        session=None,
        region=None,
        centre=None,
        objet=None,
    ):
        sujet = f"Rapport FasoIM disponible : {type_rapport}"
        message = f"""Bonjour {acteur.nom_complet or acteur.username},

Le rapport FasoIM demandé est disponible.

- Type : {type_rapport}
- Référence : {rapport_reference}
- Téléchargement : {url_telechargement}

Cordialement,
L'équipe FasoIM
"""
        return cls.planifier_email_acteur(
            acteur=acteur,
            sujet=sujet,
            message=message,
            type_message=TypesMessage.RAPPORT_DISPONIBLE,
            cle_evenement=f"RAPPORT_DISPONIBLE:{rapport_reference}",
            session=session,
            region=region,
            centre=centre,
            objet=objet,
            contexte={"type_rapport": type_rapport, "rapport_reference": str(rapport_reference)},
        )

    @classmethod
    def envoyer_aux_contacts(
        cls,
        contacts: Iterable[ContactEmail],
        *,
        sujet,
        message,
        type_message,
        cle_evenement,
        session=None,
        region=None,
        centre=None,
        contexte=None,
        task_id="",
    ):
        resultats = []
        for contact in NotificationRepository.emails_uniques(contacts):
            resultat = cls.envoyer_email(
                destinataire=contact.email,
                nom_destinataire=contact.nom,
                sujet=sujet,
                message=message,
                type_message=type_message,
                cle_evenement=cle_evenement,
                acteur=contact.acteur_id,
                immerge=contact.immerge_id,
                session=session,
                region=region,
                centre=centre,
                contexte=contexte,
                task_id=task_id,
            )
            resultats.append(resultat.as_dict())
        return resultats

    @staticmethod
    def message_bienvenue_acteur(acteur, mot_de_passe_temporaire):
        login_url = getattr(settings, "FASOIM_LOGIN_URL", None) or getattr(
            settings,
            "FRONTEND_URL",
            "http://127.0.0.1:8000/admin/",
        )
        nom = acteur.nom_complet or acteur.username
        sujet = "Bienvenue sur FasoIM"
        message = f"""Bonjour {nom},

Votre compte FasoIM a été créé.

Informations de connexion :
- Nom d'utilisateur : {acteur.username}
- Email : {acteur.email}
- Mot de passe temporaire : {mot_de_passe_temporaire}

Connectez-vous ici : {login_url}

Après votre première connexion, modifiez votre mot de passe.

Cordialement,
L'équipe FasoIM
"""
        return sujet, message

    @staticmethod
    def message_affectation_acteur(affectation, *, evenement="ATTRIBUTION"):
        acteur = affectation.acteur
        session = affectation.session
        sujet = "Nouvelle affectation FasoIM" if evenement == "ATTRIBUTION" else "Mise à jour de votre affectation FasoIM"
        lignes = [
            f"Bonjour {acteur.nom_complet or acteur.username},",
            "",
            "Votre affectation FasoIM a été mise à jour.",
            f"- Niveau : {affectation.get_niveau_affectation_display()}",
            f"- Statut : {affectation.get_statut_display()}",
            f"- Session : {session.nom if session else 'Toutes les sessions autorisées'}",
        ]
        if affectation.region_code:
            lignes.append(f"- Région : {affectation.region_code}")
        if affectation.centre_id:
            lignes.append(f"- Centre : identifiant {affectation.centre_id}")
        lignes.extend(
            [
                f"- Début : {affectation.date_debut}",
                f"- Fin : {affectation.date_fin or 'non définie'}",
                "",
                "Connectez-vous à FasoIM pour consulter votre contexte de travail.",
                "",
                "Cordialement,",
                "L'équipe FasoIM",
            ]
        )
        return sujet, "\n".join(lignes)

    @staticmethod
    def message_role_acteur(affectation_role):
        acteur = affectation_role.affectation_acteur.acteur
        sujet = "Mise à jour de votre rôle FasoIM"
        message = f"""Bonjour {acteur.nom_complet or acteur.username},

Votre rôle FasoIM a été mis à jour.

- Rôle : {affectation_role.role.libelle}
- Statut : {affectation_role.get_statut_display()}
- Date d'attribution : {affectation_role.date_attribution}
- Date d'expiration : {affectation_role.date_expiration or 'non définie'}

Connectez-vous à FasoIM pour consulter vos droits effectifs.

Cordialement,
L'équipe FasoIM
"""
        return sujet, message

    @staticmethod
    def message_permission_acteur(affectation_permission):
        acteur = affectation_permission.affectation_acteur.acteur
        sujet = "Mise à jour de vos permissions FasoIM"
        message = f"""Bonjour {acteur.nom_complet or acteur.username},

Une permission individuelle FasoIM a été mise à jour.

- Permission : {affectation_permission.permission.libelle}
- Statut : {affectation_permission.get_statut_display()}
- Date d'expiration : {affectation_permission.date_expiration or 'non définie'}

Connectez-vous à FasoIM pour consulter vos droits effectifs.

Cordialement,
L'équipe FasoIM
"""
        return sujet, message

    @staticmethod
    def message_delegation(delegation):
        cible = delegation.acteur_cible
        source = delegation.acteur_source
        objet = delegation.role.libelle if delegation.role_id else delegation.permission.libelle
        sujet = "Délégation FasoIM"
        message = f"""Bonjour {cible.nom_complet or cible.username},

{source.nom_complet or source.username} vous a accordé une délégation FasoIM.

- Type : {delegation.get_type_delegation_display()}
- Élément délégué : {objet}
- Statut : {delegation.get_statut_display()}
- Période : du {delegation.date_debut} au {delegation.date_fin}

Connectez-vous à FasoIM pour consulter cette délégation.

Cordialement,
L'équipe FasoIM
"""
        return sujet, message

    @staticmethod
    def message_decision_volontaire(inscription):
        nom = inscription.identite_affichable
        statut = inscription.get_statut_demande_display()
        sujet = f"Décision concernant votre demande FasoIM : {statut}"
        message = f"""Bonjour {nom},

Votre demande volontaire FasoIM est désormais : {statut}.

Code de suivi : {inscription.code_suivi}
{('Motif : ' + inscription.motif_decision) if inscription.motif_decision else ''}

Conservez votre code de suivi et consultez la plateforme FasoIM pour la suite.

Cordialement,
L'équipe FasoIM
"""
        return sujet, message

    @staticmethod
    def message_relais_etablissement(*, etablissement, nombre_immerges, type_information, url):
        sujet = f"Information FasoIM pour les candidats de {etablissement}"
        message = f"""Bonjour,

Une information FasoIM de type « {type_information} » est disponible pour les candidats de votre établissement : {etablissement}.

Merci d'informer vos camarades qu'ils doivent consulter individuellement leurs informations sur la plateforme officielle :
{url}

Nombre approximatif de candidats sans contact direct couverts par ce relais : {nombre_immerges}.

Aucune affectation individuelle ni donnée personnelle de vos camarades n'est transmise dans ce message.

Cordialement,
L'équipe FasoIM
"""
        return sujet, message
