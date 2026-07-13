from __future__ import annotations

import logging
import sys

from django.conf import settings

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from accounts.models import (
    Acteur,
    AffectationActeur,
    AffectationPermission,
    AffectationRole,
    DelegationActeur,
)
from incidents.models import AlerteIncident
from immerges.models import InscriptionVolontaire
from organisation.models import RegleOrganisationCentre
from sessions_app.models import SessionImmersion

from .service import NotificationService, TypesMessage


logger = logging.getLogger(__name__)




def _notifications_autorisees():
    if not getattr(settings, "NOTIFICATIONS_ENABLED", True):
        return False
    if "test" in sys.argv and not getattr(settings, "NOTIFICATIONS_ENABLE_DURING_TESTS", False):
        return False
    return True


MODELES_SUIVIS = (
    Acteur,
    AffectationActeur,
    AffectationRole,
    AffectationPermission,
    DelegationActeur,
    InscriptionVolontaire,
    SessionImmersion,
    RegleOrganisationCentre,
    AlerteIncident,
)


@receiver(pre_save)
def memoriser_etat_avant_notification(sender, instance, **kwargs):
    if not _notifications_autorisees():
        return
    if sender not in MODELES_SUIVIS or not getattr(instance, "pk", None):
        return
    try:
        instance._notifications_etat_avant = sender.objects.filter(pk=instance.pk).values().first()
    except Exception:
        logger.exception("Impossible de mémoriser l'état avant notification pour %s", sender.__name__)
        instance._notifications_etat_avant = None


def _change(instance, champ, created=False):
    if created:
        return True
    avant = getattr(instance, "_notifications_etat_avant", None) or {}
    return avant.get(champ) != getattr(instance, champ, None)


def _planifier_tache_role(code_role, **payload):
    def _lancer():
        try:
            from .tasks import notifier_acteurs_role_task

            notifier_acteurs_role_task.delay(code_role, **payload)
        except Exception:
            logger.exception("Impossible de planifier l'e-mail au rôle %s", code_role)

    transaction.on_commit(_lancer)


@receiver(post_save, sender=Acteur)
def notifier_statut_compte(sender, instance, created, **kwargs):
    if not _notifications_autorisees():
        return
    if created or not _change(instance, "statut"):
        return
    sujet = "Mise à jour de votre compte FasoIM"
    message = f"""Bonjour {instance.nom_complet or instance.username},

Le statut de votre compte FasoIM est désormais : {instance.get_statut_display()}.

Si cette modification vous semble incorrecte, contactez l'administration FasoIM.

Cordialement,
L'équipe FasoIM
"""
    NotificationService.planifier_email_acteur(
        acteur=instance,
        sujet=sujet,
        message=message,
        type_message=TypesMessage.STATUT_COMPTE_ACTEUR,
        cle_evenement=f"ACTEUR:{instance.id}:STATUT:{instance.statut}",
        objet=instance,
        contexte={"statut": instance.statut},
    )


@receiver(post_save, sender=AffectationActeur)
def notifier_affectation_acteur(sender, instance, created, **kwargs):
    if not _notifications_autorisees():
        return
    champs = [
        "statut",
        "niveau_affectation",
        "session_id",
        "region_code",
        "centre_id",
        "date_debut",
        "date_fin",
    ]
    if not created and not any(_change(instance, champ) for champ in champs):
        return
    sujet, message = NotificationService.message_affectation_acteur(
        instance,
        evenement="ATTRIBUTION" if created else "MODIFICATION",
    )
    cle = ":".join(
        [
            f"AFFECTATION_ACTEUR:{instance.id}",
            str(instance.statut),
            str(instance.session_id or "GLOBAL"),
            str(instance.region_code or ""),
            str(instance.centre_id or ""),
            str(instance.date_debut),
            str(instance.date_fin or ""),
        ]
    )
    NotificationService.planifier_email_acteur(
        acteur=instance.acteur,
        sujet=sujet,
        message=message,
        type_message=TypesMessage.AFFECTATION_ACTEUR,
        cle_evenement=cle,
        session=instance.session,
        objet=instance,
        contexte={
            "niveau_affectation": instance.niveau_affectation,
            "statut": instance.statut,
            "region_code": instance.region_code,
            "centre_id": instance.centre_id,
        },
    )


@receiver(post_save, sender=AffectationRole)
def notifier_role_acteur(sender, instance, created, **kwargs):
    if not _notifications_autorisees():
        return
    champs = ["statut", "role_id", "date_attribution", "date_expiration"]
    if not created and not any(_change(instance, champ) for champ in champs):
        return
    sujet, message = NotificationService.message_role_acteur(instance)
    NotificationService.planifier_email_acteur(
        acteur=instance.affectation_acteur.acteur,
        sujet=sujet,
        message=message,
        type_message=TypesMessage.ROLE_ACTEUR,
        cle_evenement=(
            f"ROLE_ACTEUR:{instance.id}:{instance.role_id}:{instance.statut}:"
            f"{instance.date_attribution}:{instance.date_expiration or ''}"
        ),
        session=instance.affectation_acteur.session,
        objet=instance,
        contexte={"role_code": instance.role.code, "statut": instance.statut},
    )


@receiver(post_save, sender=AffectationPermission)
def notifier_permission_acteur(sender, instance, created, **kwargs):
    if not _notifications_autorisees():
        return
    champs = ["statut", "permission_id", "date_attribution", "date_expiration"]
    if not created and not any(_change(instance, champ) for champ in champs):
        return
    sujet, message = NotificationService.message_permission_acteur(instance)
    NotificationService.planifier_email_acteur(
        acteur=instance.affectation_acteur.acteur,
        sujet=sujet,
        message=message,
        type_message=TypesMessage.PERMISSION_ACTEUR,
        cle_evenement=(
            f"PERMISSION_ACTEUR:{instance.id}:{instance.permission_id}:{instance.statut}:"
            f"{instance.date_expiration or ''}"
        ),
        session=instance.affectation_acteur.session,
        objet=instance,
        contexte={"permission_code": instance.permission.code, "statut": instance.statut},
    )


@receiver(post_save, sender=DelegationActeur)
def notifier_delegation(sender, instance, created, **kwargs):
    if not _notifications_autorisees():
        return
    champs = ["statut", "date_debut", "date_fin", "role_id", "permission_id"]
    if not created and not any(_change(instance, champ) for champ in champs):
        return
    sujet, message = NotificationService.message_delegation(instance)
    base = (
        f"DELEGATION:{instance.id}:{instance.statut}:{instance.date_debut}:"
        f"{instance.date_fin}:{instance.role_id or instance.permission_id}"
    )
    for acteur, suffixe in (
        (instance.acteur_cible, "CIBLE"),
        (instance.acteur_source, "SOURCE"),
    ):
        NotificationService.planifier_email_acteur(
            acteur=acteur,
            sujet=sujet,
            message=message,
            type_message=TypesMessage.DELEGATION_ACTEUR,
            cle_evenement=f"{base}:{suffixe}",
            session=instance.affectation_acteur.session,
            objet=instance,
            contexte={
                "type_delegation": instance.type_delegation,
                "statut": instance.statut,
                "acteur_source_id": instance.acteur_source_id,
                "acteur_cible_id": instance.acteur_cible_id,
            },
        )


@receiver(post_save, sender=InscriptionVolontaire)
def notifier_volontaire(sender, instance, created, **kwargs):
    if not _notifications_autorisees():
        return
    if created:
        sujet = "Demande volontaire FasoIM reçue"
        message = f"""Bonjour {instance.identite_affichable},

Votre demande volontaire FasoIM a bien été reçue.

Code de suivi : {instance.code_suivi}

Conservez ce code pour suivre votre demande.

Cordialement,
L'équipe FasoIM
"""
        cle = f"VOLONTAIRE:{instance.id}:RECEPTION:{instance.code_suivi}"
    elif _change(instance, "statut_demande"):
        sujet, message = NotificationService.message_decision_volontaire(instance)
        cle = f"VOLONTAIRE:{instance.id}:DECISION:{instance.statut_demande}"
    else:
        return
    NotificationService.planifier_email_apres_commit(
        destinataire=instance.email,
        nom_destinataire=instance.identite_affichable,
        sujet=sujet,
        message=message,
        type_message=TypesMessage.DECISION_VOLONTAIRE,
        cle_evenement=cle,
        session_id=instance.session_id,
        objet_type="InscriptionVolontaire",
        objet_id=instance.id,
        objet_reference=instance.code_suivi,
        contexte={"statut_demande": instance.statut_demande, "mode_contact": "DIRECT"},
    )


@receiver(post_save, sender=SessionImmersion)
def notifier_changement_session(sender, instance, created, **kwargs):
    if not _notifications_autorisees():
        return
    if created:
        return
    champs = ["statut", "date_debut", "date_fin", "date_ouverture_inscription", "date_fermeture_inscription"]
    modifies = [champ for champ in champs if _change(instance, champ)]
    if not modifies:
        return
    sujet = f"Mise à jour de la session FasoIM {instance.nom}"
    message = f"""Bonjour,

La session FasoIM « {instance.nom} » a été mise à jour.

- Statut : {instance.get_statut_display()}
- Début : {instance.date_debut}
- Fin : {instance.date_fin}

Champs importants modifiés : {', '.join(modifies)}.

Connectez-vous à FasoIM pour consulter les informations officielles.

Cordialement,
L'équipe FasoIM
"""
    for role in ("DGAS", "DIRECTEUR_REGIONAL", "RESPONSABLE_CENTRE", "FORMATEUR", "AGENT_SANTE"):
        _planifier_tache_role(
            role,
            sujet=sujet,
            message=message,
            type_message=TypesMessage.SESSION_MODIFIEE,
            cle_evenement=f"SESSION:{instance.id}:MAJ:{instance.updated_at.isoformat()}",
            session_id=instance.id,
            contexte={"champs_modifies": modifies, "statut": instance.statut},
        )


@receiver(post_save, sender=RegleOrganisationCentre)
def notifier_organisation_prete(sender, instance, created, **kwargs):
    if not _notifications_autorisees():
        return
    if instance.statut != RegleOrganisationCentre.Statut.PRETE_PUBLICATION:
        return
    if not created and not _change(instance, "statut"):
        return
    sujet = "Organisation d'un centre prête pour publication"
    message = f"""Bonjour,

L'organisation interne du centre {instance.centre.nom} est prête pour contrôle et publication.

- Session : {instance.session.nom}
- Région : {instance.centre.region.nom}
- Centre : {instance.centre.nom}

Connectez-vous à FasoIM pour effectuer le contrôle.

Cordialement,
L'équipe FasoIM
"""
    for role in ("DGAS", "DIRECTEUR_REGIONAL"):
        _planifier_tache_role(
            role,
            sujet=sujet,
            message=message,
            type_message=TypesMessage.ORGANISATION_PRETE,
            cle_evenement=f"ORGANISATION_PRETE:{instance.id}:{instance.updated_at.isoformat()}",
            session_id=instance.session_id,
            region_code=instance.centre.region.code,
            centre_id=instance.centre_id,
            contexte={
                "regle_organisation_id": instance.id,
                "centre_id": instance.centre_id,
                "statut": instance.statut,
            },
        )


@receiver(post_save, sender=AlerteIncident)
def notifier_incident_important(sender, instance, created, **kwargs):
    if not _notifications_autorisees():
        return
    grave = instance.niveau_gravite in {
        AlerteIncident.NiveauGravite.ELEVE,
        AlerteIncident.NiveauGravite.CRITIQUE,
    }
    if not grave or not instance.est_ouvert:
        return
    if not created and not (_change(instance, "niveau_gravite") or _change(instance, "niveau_escalade")):
        return
    sujet = "Incident important dans FasoIM"
    message = f"""Bonjour,

Un incident important nécessite l'attention des acteurs autorisés dans votre périmètre.

- Niveau : {instance.get_niveau_gravite_display()}
- Session : {instance.session.nom if instance.session_id else 'Non précisée'}
- Centre : {instance.centre.nom if instance.centre_id else 'Non précisé'}

Consultez FasoIM selon vos droits. Aucun détail médical ou sensible n'est transmis par e-mail.

Cordialement,
L'équipe FasoIM
"""
    roles = ["DGAS"]
    if instance.region_id or instance.centre_id:
        roles.append("DIRECTEUR_REGIONAL")
    if instance.centre_id:
        roles.append("RESPONSABLE_CENTRE")
    for role in roles:
        _planifier_tache_role(
            role,
            sujet=sujet,
            message=message,
            type_message=TypesMessage.INCIDENT_IMPORTANT,
            cle_evenement=(
                f"INCIDENT:{instance.id}:GRAVITE:{instance.niveau_gravite}:"
                f"ESCALADE:{instance.niveau_escalade}"
            ),
            session_id=instance.session_id,
            region_code=instance.region.code if instance.region_id else None,
            centre_id=instance.centre_id,
            contexte={
                "incident_id": instance.id,
                "niveau_gravite": instance.niveau_gravite,
                "niveau_escalade": instance.niveau_escalade,
            },
        )
