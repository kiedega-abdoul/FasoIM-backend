from __future__ import annotations

import logging
from collections import defaultdict

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from accounts.models import Acteur
from affectations.models import CentreImmersion, RegionImmersion
from immerges.models import Immerge
from sessions_app.models import SessionImmersion

from audit.models import JournalAction
from audit.service import JournalActionService

from .repository import NotificationRepository
from .service import ErreurEnvoiEmail, NotificationService, TypesMessage


logger = logging.getLogger(__name__)

TTL_PROGRESSION = 60 * 60 * 24


def _progression_key(task_id):
    return f"notifications:progression:{task_id}"


def _set_progression(task_id, **donnees):
    valeur = {
        "task_id": task_id,
        "statut": donnees.pop("statut", "EN_COURS"),
        "progression": donnees.pop("progression", 0),
        **donnees,
    }
    cache.set(_progression_key(task_id), valeur, TTL_PROGRESSION)
    return valeur


def lire_progression(task_id):
    return cache.get(_progression_key(task_id)) or {
        "task_id": task_id,
        "statut": "INCONNUE",
        "progression": 0,
        "message": "Aucune progression disponible.",
    }


def _objet(model, identifiant):
    if not identifiant:
        return None
    return model.objects.filter(id=identifiant).first()


@shared_task(
    bind=True,
    name="notifications.envoyer_email",
    max_retries=3,
    default_retry_delay=60,
)
def envoyer_email_task(self, payload):
    payload = dict(payload or {})
    tentative = int(getattr(self.request, "retries", 0)) + 1
    acteur = _objet(Acteur, payload.pop("acteur_id", None))
    immerge = _objet(Immerge, payload.pop("immerge_id", None))
    session = _objet(SessionImmersion, payload.pop("session_id", None))
    region = _objet(RegionImmersion, payload.pop("region_id", None))
    centre = _objet(CentreImmersion, payload.pop("centre_id", None))
    payload.pop("nom_destinataire", None)

    try:
        resultat = NotificationService.envoyer_email(
            **payload,
            acteur=acteur,
            immerge=immerge,
            session=session,
            region=region,
            centre=centre,
            task_id=self.request.id,
            tentative=tentative,
        )
        return resultat.as_dict()
    except ErreurEnvoiEmail as exc:
        logger.warning(
            "Échec d'envoi notification %s, tentative %s",
            payload.get("type_message"),
            tentative,
        )
        delai = int(getattr(settings, "NOTIFICATIONS_RETRY_DELAY_SECONDS", 60)) * tentative
        raise self.retry(exc=exc, countdown=max(10, delai))


@shared_task(
    bind=True,
    name="notifications.envoyer_emails_masse",
    max_retries=1,
    default_retry_delay=120,
)
def envoyer_emails_masse_task(self, messages, contexte_global=None):
    messages = list(messages or [])
    total = len(messages)
    _set_progression(
        self.request.id,
        statut="EN_COURS",
        progression=0,
        total=total,
        traites=0,
        envoyes=0,
        deja_envoyes=0,
        echecs=0,
        message="Envoi massif démarré.",
    )
    envoyes = deja_envoyes = echecs = 0
    resultats = []
    for index, message in enumerate(messages, start=1):
        payload = dict(message or {})
        payload["contexte"] = {**(contexte_global or {}), **(payload.get("contexte") or {})}
        payload["task_id"] = self.request.id
        try:
            resultat = NotificationService.envoyer_email(**payload)
            resultats.append(resultat.as_dict())
            if resultat.envoye:
                envoyes += 1
            elif resultat.statut == NotificationService.STATUT_DEJA_ENVOYE:
                deja_envoyes += 1
            else:
                echecs += 1
        except Exception as exc:
            echecs += 1
            resultats.append({
                "envoye": False,
                "statut": "ECHEC",
                "motif": str(exc)[:500],
                "destinataire_masque": NotificationService.masquer_email(payload.get("destinataire")),
            })
        progression = int(index * 100 / max(total, 1))
        _set_progression(
            self.request.id,
            statut="EN_COURS",
            progression=progression,
            total=total,
            traites=index,
            envoyes=envoyes,
            deja_envoyes=deja_envoyes,
            echecs=echecs,
            message="Envoi massif en cours.",
        )

    statut = "TERMINEE" if echecs == 0 else ("PARTIELLE" if envoyes or deja_envoyes else "ECHEC")
    final = _set_progression(
        self.request.id,
        statut=statut,
        progression=100,
        total=total,
        traites=total,
        envoyes=envoyes,
        deja_envoyes=deja_envoyes,
        echecs=echecs,
        message="Envoi massif terminé.",
        resultats=resultats[:200],
    )
    return final


@shared_task(
    bind=True,
    name="notifications.informer_immerges",
    max_retries=1,
    default_retry_delay=120,
)
def informer_immerges_task(
    self,
    immerge_ids,
    *,
    type_message,
    sujet,
    message,
    cle_evenement,
    url_portail="",
    contexte_global=None,
    region_id=None,
    centre_id=None,
):
    """Informe directement les immergés joignables puis les relais examens.

    Les immergés sans e-mail sont regroupés par établissement. Chaque relais ne
    reçoit qu'un message collectif, sans liste nominative ni affectation privée.
    """
    ids = list(dict.fromkeys(int(i) for i in (immerge_ids or [])))
    queryset = Immerge.objects.filter(id__in=ids, deleted_at__isnull=True).select_related("session")
    total = len(ids)
    envoyes_directs = deja_envoyes = echecs = 0
    sans_contact = defaultdict(list)
    traites = 0

    _set_progression(
        self.request.id,
        statut="EN_COURS",
        progression=0,
        total=total,
        traites=0,
        envoyes_directs=0,
        relais_envoyes=0,
        sans_contact=0,
        echecs=0,
        message="Information des immergés démarrée.",
    )

    for immerge in queryset.iterator(chunk_size=int(getattr(settings, "NOTIFICATIONS_BATCH_SIZE", 200))):
        contact = NotificationRepository.contact_immerge(immerge)
        if contact:
            try:
                resultat = NotificationService.envoyer_email(
                    destinataire=contact.email,
                    sujet=sujet,
                    message=message,
                    type_message=type_message,
                    cle_evenement=f"{cle_evenement}:IMMERGE:{immerge.id}",
                    immerge=immerge,
                    session=immerge.session,
                    region=region_id,
                    centre=centre_id,
                    contexte={**(contexte_global or {}), "mode_contact": "DIRECT"},
                    task_id=self.request.id,
                )
                if resultat.envoye:
                    envoyes_directs += 1
                elif resultat.statut == NotificationService.STATUT_DEJA_ENVOYE:
                    deja_envoyes += 1
                else:
                    echecs += 1
            except Exception:
                echecs += 1
        else:
            contexte_examen = NotificationRepository.contexte_examen(immerge)
            if contexte_examen:
                cle_groupe = (
                    contexte_examen["session_id"],
                    contexte_examen["type_examen"],
                    contexte_examen["etablissement"].casefold(),
                )
                sans_contact[cle_groupe].append(immerge.id)
            else:
                JournalActionService.journaliser_refus(
                    code_action="envoyer_information_immerge",
                    module_source="notifications",
                    origine=JournalAction.Origine.CELERY,
                    canal=JournalAction.Canal.EMAIL,
                    immerge=immerge,
                    session=immerge.session,
                    motif="AUCUN_EMAIL_DIRECT_ET_AUCUN_RELAIS_APPLICABLE",
                    contexte={
                        "type_message": type_message,
                        "cle_deduplication": f"{cle_evenement}:IMMERGE:{immerge.id}",
                        "mode_contact": "INDISPONIBLE",
                    },
                    task_id=self.request.id,
                )
                echecs += 1
        traites += 1
        _set_progression(
            self.request.id,
            statut="EN_COURS",
            progression=int(traites * 80 / max(total, 1)),
            total=total,
            traites=traites,
            envoyes_directs=envoyes_directs,
            deja_envoyes=deja_envoyes,
            relais_envoyes=0,
            sans_contact=sum(len(v) for v in sans_contact.values()),
            echecs=echecs,
            message="Information directe en cours.",
        )

    relais_envoyes = 0
    etablissements_sans_relais = 0
    url = url_portail or getattr(settings, "FASOIM_PUBLIC_URL", "http://127.0.0.1:3000")
    limite_relais = int(getattr(settings, "NOTIFICATIONS_MAX_RELAIS_ETABLISSEMENT", 3))
    for (session_id, type_examen, etablissement_normalise), immerges_groupe in sans_contact.items():
        # On reprend l'orthographe réelle depuis la première source.
        premier = Immerge.objects.filter(id=immerges_groupe[0]).select_related("session").first()
        contexte_examen = NotificationRepository.contexte_examen(premier) if premier else None
        etablissement = contexte_examen["etablissement"] if contexte_examen else etablissement_normalise
        contacts = NotificationRepository.relais_etablissement(
            session_id=session_id,
            type_examen=type_examen,
            etablissement=etablissement,
            exclure_immerge_ids=immerges_groupe,
            limite=limite_relais,
        )
        if not contacts:
            etablissements_sans_relais += 1
            JournalActionService.journaliser_refus(
                code_action="informer_relais_etablissement",
                module_source="notifications",
                origine=JournalAction.Origine.CELERY,
                canal=JournalAction.Canal.EMAIL,
                session=session_id,
                motif="AUCUN_RELAIS_EMAIL_DANS_ETABLISSEMENT",
                contexte={
                    "type_message": type_message,
                    "etablissement": etablissement,
                    "nombre_immerges_couverts": len(immerges_groupe),
                    "cle_deduplication": f"{cle_evenement}:ETABLISSEMENT:{__import__('hashlib').sha256(etablissement_normalise.encode()).hexdigest()[:24]}",
                },
                task_id=self.request.id,
            )
            continue
        sujet_relais, message_relais = NotificationService.message_relais_etablissement(
            etablissement=etablissement,
            nombre_immerges=len(immerges_groupe),
            type_information=type_message,
            url=url,
        )
        for contact in contacts:
            try:
                resultat = NotificationService.envoyer_email(
                    destinataire=contact.email,
                    sujet=sujet_relais,
                    message=message_relais,
                    type_message=TypesMessage.RELAIS_ETABLISSEMENT,
                    cle_evenement=f"{cle_evenement}:ETABLISSEMENT:{etablissement_normalise}",
                    immerge=contact.immerge_id,
                    session=session_id,
                    region=region_id,
                    centre=centre_id,
                    contexte={
                        **(contexte_global or {}),
                        "mode_contact": "RELAIS_ETABLISSEMENT",
                        "etablissement": etablissement,
                        "nombre_immerges_couverts": len(immerges_groupe),
                    },
                    task_id=self.request.id,
                )
                if resultat.envoye:
                    relais_envoyes += 1
                elif resultat.statut == NotificationService.STATUT_DEJA_ENVOYE:
                    deja_envoyes += 1
                else:
                    echecs += 1
            except Exception:
                echecs += 1

    statut = "TERMINEE" if echecs == 0 and etablissements_sans_relais == 0 else "PARTIELLE"
    final = _set_progression(
        self.request.id,
        statut=statut,
        progression=100,
        total=total,
        traites=traites,
        envoyes_directs=envoyes_directs,
        deja_envoyes=deja_envoyes,
        relais_envoyes=relais_envoyes,
        immerges_sans_contact_direct=sum(len(v) for v in sans_contact.values()),
        etablissements_sans_relais=etablissements_sans_relais,
        echecs=echecs,
        message="Information des immergés terminée.",
    )
    return final


@shared_task(
    bind=True,
    name="notifications.notifier_acteurs_role",
    max_retries=1,
    default_retry_delay=120,
)
def notifier_acteurs_role_task(
    self,
    code_role,
    *,
    sujet,
    message,
    type_message,
    cle_evenement,
    session_id=None,
    region_code=None,
    centre_id=None,
    contexte=None,
):
    contacts = NotificationRepository.acteurs_par_role(
        code_role,
        session_id=session_id,
        region_code=region_code,
        centre_id=centre_id,
    )
    total = len(contacts)
    envoyes = deja_envoyes = echecs = 0
    _set_progression(
        self.request.id,
        statut="EN_COURS",
        progression=0,
        total=total,
        traites=0,
        envoyes=0,
        deja_envoyes=0,
        echecs=0,
        message=f"Information du rôle {code_role} démarrée.",
    )
    for index, contact in enumerate(contacts, start=1):
        try:
            resultat = NotificationService.envoyer_email(
                destinataire=contact.email,
                sujet=sujet,
                message=message,
                type_message=type_message,
                cle_evenement=f"{cle_evenement}:ACTEUR:{contact.acteur_id}",
                acteur=contact.acteur_id,
                session=session_id,
                centre=centre_id,
                contexte={**(contexte or {}), "role_destinataire": code_role},
                task_id=self.request.id,
            )
            if resultat.envoye:
                envoyes += 1
            elif resultat.statut == NotificationService.STATUT_DEJA_ENVOYE:
                deja_envoyes += 1
            else:
                echecs += 1
        except Exception:
            echecs += 1
        _set_progression(
            self.request.id,
            statut="EN_COURS",
            progression=int(index * 100 / max(total, 1)),
            total=total,
            traites=index,
            envoyes=envoyes,
            deja_envoyes=deja_envoyes,
            echecs=echecs,
            message=f"Information du rôle {code_role} en cours.",
        )
    statut = "TERMINEE" if echecs == 0 else ("PARTIELLE" if envoyes or deja_envoyes else "ECHEC")
    return _set_progression(
        self.request.id,
        statut=statut,
        progression=100,
        total=total,
        traites=total,
        envoyes=envoyes,
        deja_envoyes=deja_envoyes,
        echecs=echecs,
        message=f"Information du rôle {code_role} terminée.",
    )
