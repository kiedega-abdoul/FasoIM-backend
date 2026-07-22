import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import (
    Acteur,
    AffectationActeur,
    AffectationPermission,
    AffectationRole,
    DelegationActeur,
    DemandePermission,
    Permission,
    Role,
    RolePermission,
)
from .access_context import obtenir_affectation_courante_id
from .repository import (
    ActeurRepository,
    AffectationActeurRepository,
    AffectationPermissionRepository,
    AffectationRoleRepository,
    ControleAccesRepository,
    DelegationActeurRepository,
    DemandePermissionRepository,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
)

logger = logging.getLogger(__name__)

MOT_DE_PASSE_ACTEUR_PAR_DEFAUT = getattr(settings, "DEFAULT_ACTOR_PASSWORD", "password")


@dataclass(frozen=True)
class ResultatControleAcces:
    autorise: bool
    motif: str = ""
    affectation: AffectationActeur | None = None


class ServiceBase:
    """Outils communs aux services métier accounts."""

    @staticmethod
    def normaliser_texte(valeur):
        if valeur is None:
            return ""
        return str(valeur).strip()

    @staticmethod
    def normaliser_code(valeur):
        valeur = ServiceBase.normaliser_texte(valeur)
        if not valeur:
            return ""
        return slugify(valeur).replace("-", "_").upper()

    @staticmethod
    def identifiant(objet_ou_id):
        return getattr(objet_ou_id, "id", objet_ou_id)

    @staticmethod
    def maintenant():
        return timezone.now()

    @staticmethod
    def aujourd_hui():
        return timezone.localdate()


class ServiceAsynchroneAccounts:
    """Points d'entrée Celery/Redis utilisés par les services accounts."""

    @staticmethod
    def envoyer_email_bienvenue_apres_commit(acteur_id, mot_de_passe_temporaire):
        def _planifier():
            try:
                from .tasks import envoyer_email_bienvenue_acteur_task

                envoyer_email_bienvenue_acteur_task.delay(acteur_id, mot_de_passe_temporaire)
            except Exception:
                logger.exception("Impossible de planifier l'email de bienvenue de l'acteur %s", acteur_id)

        transaction.on_commit(_planifier)

    @staticmethod
    def supprimer_acteur_en_cascade_apres_commit(acteur_id, auteur_id=None):
        def _planifier():
            try:
                from .tasks import supprimer_acteur_logiquement_en_cascade_task

                supprimer_acteur_logiquement_en_cascade_task.delay(acteur_id, auteur_id)
            except Exception:
                logger.exception("Impossible de planifier la suppression logique de l'acteur %s", acteur_id)

        transaction.on_commit(_planifier)

    @staticmethod
    def recalculer_cache_permissions_apres_commit(acteur_id):
        def _planifier():
            try:
                from .tasks import recalculer_cache_permissions_acteur_task

                recalculer_cache_permissions_acteur_task.delay(acteur_id)
            except Exception:
                logger.exception("Impossible de planifier le recalcul des permissions de l'acteur %s", acteur_id)

        transaction.on_commit(_planifier)




class CreationSubordonneeService(ServiceBase):
    """Règles communes pour créer des collaborateurs sans dépasser ses droits."""

    RANGS = {
        AffectationActeur.NiveauAffectation.CENTRE: 1,
        AffectationActeur.NiveauAffectation.REGION: 2,
        AffectationActeur.NiveauAffectation.NATIONAL: 3,
        AffectationActeur.NiveauAffectation.PLATEFORME: 4,
    }

    @staticmethod
    def affectation_source(acteur):
        if getattr(acteur, "is_superuser", False):
            return None
        affectation_id = obtenir_affectation_courante_id()
        affectation = None
        if affectation_id not in (None, -1):
            affectation = AffectationActeurRepository.get_active_by_id(affectation_id)
        if affectation is None or affectation.acteur_id != acteur.id:
            raise ValidationError("Choisissez une affectation active avant de créer ou déléguer.")
        return affectation

    @staticmethod
    def verifier_perimetre(source, *, niveau, session_id=None, region_code=None, centre_id=None):
        if source is None:
            return
        if CreationSubordonneeService.RANGS.get(niveau, 0) > CreationSubordonneeService.RANGS.get(source.niveau_affectation, 0):
            raise ValidationError("Le périmètre cible dépasse celui du créateur.")
        if source.session_id and session_id != source.session_id:
            raise ValidationError("La session cible doit être celle de l'affectation du créateur.")
        if source.niveau_affectation == AffectationActeur.NiveauAffectation.REGION:
            if region_code and region_code != source.region_code:
                raise ValidationError("La région cible dépasse le périmètre du créateur.")
            if centre_id:
                from affectations.models import CentreImmersion
                ok = CentreImmersion.objects.filter(id=centre_id, region__code=source.region_code, deleted_at__isnull=True).exists()
                if not ok:
                    raise ValidationError("Le centre cible n'appartient pas à la région du créateur.")
        if source.niveau_affectation == AffectationActeur.NiveauAffectation.CENTRE and centre_id != source.centre_id:
            raise ValidationError("Le centre cible doit être celui du créateur.")

    @staticmethod
    def verifier_role_creable(acteur, *, niveau, perimetre_autorise):
        source = CreationSubordonneeService.affectation_source(acteur)
        if source is None:
            return source
        niveaux = list(AffectationRole.objects.filter(affectation_acteur=source, statut=AffectationRole.Statut.ACTIF, deleted_at__isnull=True).values_list("role__niveau", flat=True))
        if not niveaux or niveau < min(niveaux):
            raise ValidationError("Le rôle créé doit être de niveau égal ou inférieur au vôtre.")
        if CreationSubordonneeService.RANGS.get(perimetre_autorise, 0) > CreationSubordonneeService.RANGS.get(source.niveau_affectation, 0):
            raise ValidationError("Le rôle créé possède un périmètre trop large.")
        return source

    @staticmethod
    def verifier_permission_attribuable(acteur, permission):
        source = CreationSubordonneeService.affectation_source(acteur)
        if source is None:
            return source
        permissions = ControleAccesRepository.get_permission_codes_acteur(acteur, source)
        if permission.code not in permissions:
            raise ValidationError("Vous ne pouvez attribuer qu'une permission que vous possédez.")
        return source


class ActeurService(ServiceBase):
    """Gestion métier des acteurs internes FasoIM."""

    @staticmethod
    def generer_username(first_name, last_name, email=None):
        base = slugify(f"{first_name or ''} {last_name or ''}".strip())
        if not base and email:
            base = slugify(str(email).split("@")[0])
        if not base:
            base = "acteur"

        username = base
        compteur = 1
        while ActeurRepository.username_existe(username):
            compteur += 1
            username = f"{base}{compteur}"
        return username[:150]

    @staticmethod
    @transaction.atomic
    def creer_acteur(
        *,
        email,
        first_name,
        last_name,
        username=None,
        telephone=None,
        titre="",
        organisation="",
        signature_image=None,
        cachet_image=None,
        created_by=None,
        is_staff=False,
        is_superuser=False,
        envoyer_email_bienvenue=True,
    ):
        email = ActeurService.normaliser_texte(email).lower()
        first_name = ActeurService.normaliser_texte(first_name)
        last_name = ActeurService.normaliser_texte(last_name)
        username = ActeurService.normaliser_texte(username) or ActeurService.generer_username(first_name, last_name, email)
        telephone = ActeurService.normaliser_texte(telephone) or None

        if not email:
            raise ValidationError({"email": "L'email est obligatoire."})
        if not first_name:
            raise ValidationError({"first_name": "Le prénom est obligatoire."})
        if not last_name:
            raise ValidationError({"last_name": "Le nom est obligatoire."})
        if ActeurRepository.email_existe(email):
            raise ValidationError({"email": "Cet email est déjà utilisé."})
        if ActeurRepository.username_existe(username):
            raise ValidationError({"username": "Ce nom d'utilisateur est déjà utilisé."})
        if telephone and ActeurRepository.telephone_existe(telephone):
            raise ValidationError({"telephone": "Ce téléphone est déjà utilisé."})

        acteur = Acteur(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            telephone=telephone,
            titre=ActeurService.normaliser_texte(titre),
            organisation=ActeurService.normaliser_texte(organisation),
            signature_image=signature_image,
            cachet_image=cachet_image,
            statut=Acteur.Statut.ACTIF,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
            created_by=created_by,
        )
        acteur.set_password(MOT_DE_PASSE_ACTEUR_PAR_DEFAUT)
        acteur.full_clean()
        acteur.save()

        if envoyer_email_bienvenue:
            ServiceAsynchroneAccounts.envoyer_email_bienvenue_apres_commit(
                acteur.id,
                MOT_DE_PASSE_ACTEUR_PAR_DEFAUT,
            )

        return acteur

    @staticmethod
    @transaction.atomic
    def modifier_profil(
        acteur,
        *,
        first_name=None,
        last_name=None,
        email=None,
        telephone=None,
        titre=None,
        organisation=None,
        signature_image=None,
        cachet_image=None,
    ):
        acteur = ActeurRepository.get_actif_by_id(ActeurService.identifiant(acteur))
        if not acteur:
            raise ValidationError("Acteur introuvable ou inactif.")

        if first_name is not None:
            acteur.first_name = ActeurService.normaliser_texte(first_name)
        if last_name is not None:
            acteur.last_name = ActeurService.normaliser_texte(last_name)
        if email is not None:
            email = ActeurService.normaliser_texte(email).lower()
            if not email:
                raise ValidationError({"email": "L'email est obligatoire."})
            if ActeurRepository.email_existe(email, exclude_id=acteur.id):
                raise ValidationError({"email": "Cet email est déjà utilisé."})
            acteur.email = email
        if telephone is not None:
            telephone = ActeurService.normaliser_texte(telephone) or None
            if telephone and ActeurRepository.telephone_existe(telephone, exclude_id=acteur.id):
                raise ValidationError({"telephone": "Ce téléphone est déjà utilisé."})
            acteur.telephone = telephone
        if titre is not None:
            acteur.titre = ActeurService.normaliser_texte(titre)
        if organisation is not None:
            acteur.organisation = ActeurService.normaliser_texte(organisation)
        if signature_image is not None:
            acteur.signature_image = signature_image
        if cachet_image is not None:
            acteur.cachet_image = cachet_image

        acteur.full_clean()
        acteur.save()
        return acteur

    @staticmethod
    @transaction.atomic
    def changer_mot_de_passe(acteur, nouveau_mot_de_passe):
        acteur = ActeurRepository.get_actif_by_id(ActeurService.identifiant(acteur))
        if not acteur:
            raise ValidationError("Acteur introuvable ou inactif.")
        if not nouveau_mot_de_passe:
            raise ValidationError({"password": "Le nouveau mot de passe est obligatoire."})

        acteur.set_password(nouveau_mot_de_passe)
        acteur.save(update_fields=["password"])
        return acteur

    @staticmethod
    @transaction.atomic
    def desactiver_acteur(acteur, *, auteur=None):
        acteur = ActeurRepository.get_actif_by_id(ActeurService.identifiant(acteur))
        if not acteur:
            raise ValidationError("Acteur introuvable ou déjà inactif.")

        acteur.is_active = False
        acteur.statut = Acteur.Statut.DESACTIVE
        acteur.save(update_fields=["is_active", "statut"])

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(acteur.id)
        return acteur

    @staticmethod
    @transaction.atomic
    def reactiver_acteur(acteur, *, auteur=None):
        acteur = ActeurRepository.get_any_by_id(ActeurService.identifiant(acteur))
        if not acteur or acteur.deleted_at is not None:
            raise ValidationError("Acteur introuvable ou supprimé logiquement.")

        acteur.is_active = True
        acteur.statut = Acteur.Statut.ACTIF
        acteur.save(update_fields=["is_active", "statut"])

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(acteur.id)
        return acteur

    @staticmethod
    def supprimer_logiquement_async(acteur, *, auteur=None):
        acteur_id = ActeurService.identifiant(acteur)
        auteur_id = ActeurService.identifiant(auteur) if auteur else None
        ServiceAsynchroneAccounts.supprimer_acteur_en_cascade_apres_commit(acteur_id, auteur_id)
        return True

    @staticmethod
    @transaction.atomic
    def supprimer_logiquement_synchrone(acteur, *, auteur=None):
        acteur = Acteur.objects.select_for_update().filter(id=ActeurService.identifiant(acteur)).first()
        if not acteur or acteur.deleted_at is not None:
            return None

        maintenant = ActeurService.maintenant()
        suffixe = f"deleted-{acteur.id}-{int(maintenant.timestamp())}"

        acteur.username = f"{suffixe}-{acteur.username}"[:150]
        acteur.email = f"{suffixe}@deleted.fasoim.local"
        if acteur.telephone:
            acteur.telephone = suffixe[:30]
        acteur.is_active = False
        acteur.statut = Acteur.Statut.DESACTIVE
        acteur.deleted_at = maintenant
        acteur.save()

        affectation_ids = list(
            AffectationActeur.objects.filter(
                acteur_id=acteur.id,
                deleted_at__isnull=True,
            ).values_list("id", flat=True)
        )

        AffectationRole.objects.filter(
            affectation_acteur_id__in=affectation_ids,
            deleted_at__isnull=True,
        ).update(statut=AffectationRole.Statut.RETIRE, deleted_at=maintenant)

        AffectationPermission.objects.filter(
            affectation_acteur_id__in=affectation_ids,
            deleted_at__isnull=True,
        ).update(statut=AffectationPermission.Statut.RETIREE, deleted_at=maintenant)

        DemandePermission.objects.filter(
            acteur_id=acteur.id,
            statut=DemandePermission.Statut.EN_ATTENTE,
            deleted_at__isnull=True,
        ).update(statut=DemandePermission.Statut.ANNULEE, date_decision=maintenant, deleted_at=maintenant)

        DelegationActeur.objects.filter(
            acteur_source_id=acteur.id,
            deleted_at__isnull=True,
        ).update(statut=DelegationActeur.Statut.ANNULEE, deleted_at=maintenant)

        DelegationActeur.objects.filter(
            acteur_cible_id=acteur.id,
            deleted_at__isnull=True,
        ).update(statut=DelegationActeur.Statut.ANNULEE, deleted_at=maintenant)

        AffectationActeur.objects.filter(
            id__in=affectation_ids,
            deleted_at__isnull=True,
        ).update(statut=AffectationActeur.Statut.ANNULEE, deleted_at=maintenant)

        return acteur


class RoleService(ServiceBase):
    """Gestion métier des rôles."""

    RANGS_PERIMETRES = {
        Role.Perimetre.CENTRE: 1,
        Role.Perimetre.REGION: 2,
        Role.Perimetre.NATIONAL: 3,
        Role.Perimetre.PLATEFORME: 4,
    }

    @staticmethod
    @transaction.atomic
    def creer_role_systeme(*, code, libelle, niveau, perimetre_autorise, description="", est_modifiable=False):
        code = RoleService.normaliser_code(code)
        if not code:
            raise ValidationError({"code": "Le code du rôle est obligatoire."})
        if RoleRepository.code_existe(code):
            raise ValidationError({"code": "Ce code de rôle existe déjà."})

        role = Role(
            code=code,
            libelle=RoleService.normaliser_texte(libelle),
            description=RoleService.normaliser_texte(description),
            niveau=niveau,
            perimetre_autorise=perimetre_autorise,
            est_systeme=True,
            est_modifiable=est_modifiable,
            statut=Role.Statut.ACTIF,
        )
        role.full_clean()
        role.save()
        return role

    @staticmethod
    @transaction.atomic
    def creer_role_personnalise(*, libelle, niveau, perimetre_autorise, description="", cree_par=None):
        libelle = RoleService.normaliser_texte(libelle)
        if cree_par is not None and not getattr(cree_par, "is_superuser", False):
            CreationSubordonneeService.verifier_role_creable(cree_par, niveau=niveau, perimetre_autorise=perimetre_autorise)
        if not libelle:
            raise ValidationError({"libelle": "Le libellé du rôle est obligatoire."})

        base = RoleService.normaliser_code(libelle)
        code = f"ROLE_{base}"
        compteur = 1
        while RoleRepository.code_existe(code):
            compteur += 1
            code = f"ROLE_{base}_{compteur}"

        role = Role(
            code=code,
            libelle=libelle,
            description=RoleService.normaliser_texte(description),
            niveau=niveau,
            perimetre_autorise=perimetre_autorise,
            est_systeme=False,
            est_modifiable=True,
            statut=Role.Statut.ACTIF,
        )
        role.full_clean()
        role.save()
        return role

    @staticmethod
    @transaction.atomic
    def desactiver_role(role):
        role = RoleRepository.get_actif_by_id(RoleService.identifiant(role))
        if not role:
            raise ValidationError("Rôle introuvable ou inactif.")
        if role.est_systeme and not role.est_modifiable:
            raise ValidationError("Ce rôle système n'est pas désactivable librement.")

        role.statut = Role.Statut.INACTIF
        role.save(update_fields=["statut", "updated_at"])
        return role

    @staticmethod
    def lister_roles_attribuables(acteur, affectation_cible):
        """Liste les rôles que l'acteur courant peut ajouter à l'affectation cible."""

        acteur = ActeurRepository.get_actif_by_id(RoleService.identifiant(acteur))
        affectation_cible = AffectationActeurRepository.non_supprimes().filter(
            id=RoleService.identifiant(affectation_cible)
        ).exclude(
            statut__in=[
                AffectationActeur.Statut.TERMINEE,
                AffectationActeur.Statut.ANNULEE,
            ]
        ).first()
        if not acteur:
            raise ValidationError("Acteur introuvable ou inactif.")
        if not affectation_cible:
            raise ValidationError("Affectation introuvable.")
        if affectation_cible.statut != AffectationActeur.Statut.ACTIVE:
            return RoleRepository.actifs().none()

        if getattr(acteur, "is_superuser", False):
            niveau_minimum = 0
        else:
            affectation_source_id = obtenir_affectation_courante_id()
            affectation_source = None
            if affectation_source_id not in (None, -1):
                affectation_source = AffectationActeurRepository.get_active_by_id(affectation_source_id)
            if affectation_source is None or affectation_source.acteur_id != acteur.id:
                raise ValidationError(
                    "Choisissez votre contexte de travail avant d'ajouter un rôle."
                )

            resultat = ControleAccesService.acteur_peut(
                acteur,
                "attribuer_role",
                affectation=affectation_source,
                session_id=affectation_cible.session_id,
                region_code=affectation_cible.region_code or None,
                centre_id=affectation_cible.centre_id,
            )
            if not resultat.autorise:
                raise ValidationError("Vous ne pouvez pas ajouter un rôle sur cette affectation.")

            niveaux_source = list(
                AffectationRole.objects.filter(
                    affectation_acteur=affectation_source,
                    statut=AffectationRole.Statut.ACTIF,
                    deleted_at__isnull=True,
                ).values_list("role__niveau", flat=True)
            )
            if not niveaux_source:
                return RoleRepository.actifs().none()
            niveau_minimum = min(niveaux_source)

        rang_affectation = RoleService.RANGS_PERIMETRES.get(affectation_cible.niveau_affectation, 0)
        roles_attribues = AffectationRole.objects.filter(
            affectation_acteur=affectation_cible,
            statut=AffectationRole.Statut.ACTIF,
            deleted_at__isnull=True,
        ).values("role_id")

        return (
            RoleRepository.actifs()
            .filter(niveau__gte=niveau_minimum)
            .exclude(id__in=roles_attribues)
            .filter(
                perimetre_autorise__in=[
                    perimetre
                    for perimetre, rang in RoleService.RANGS_PERIMETRES.items()
                    if rang <= rang_affectation
                ]
            )
            .order_by("niveau", "code")
        )


class PermissionService(ServiceBase):
    """Gestion contrôlée du catalogue fermé des permissions."""

    @staticmethod
    @transaction.atomic
    def creer_permission_systeme(*, code, libelle, module, description=""):
        code = PermissionService.normaliser_texte(code)
        if not code:
            raise ValidationError({"code": "Le code de permission est obligatoire."})
        if PermissionRepository.code_existe(code):
            raise ValidationError({"code": "Cette permission existe déjà."})

        permission = Permission(
            code=code,
            libelle=PermissionService.normaliser_texte(libelle),
            module=PermissionService.normaliser_texte(module),
            description=PermissionService.normaliser_texte(description),
            est_systeme=True,
            statut=Permission.Statut.ACTIVE,
        )
        permission.full_clean()
        permission.save()
        return permission

    @staticmethod
    @transaction.atomic
    def desactiver_permission(permission):
        permission = PermissionRepository.get_actif_by_id(PermissionService.identifiant(permission))
        if not permission:
            raise ValidationError("Permission introuvable ou inactive.")

        permission.statut = Permission.Statut.INACTIVE
        permission.save(update_fields=["statut", "updated_at"])
        return permission


class RolePermissionService(ServiceBase):
    """Gestion des permissions attachées aux rôles."""

    @staticmethod
    @transaction.atomic
    def ajouter_permission(role, permission, *, est_delegable=False, perimetre_delegation_max="", attribue_par=None):
        role = RoleRepository.get_actif_by_id(RolePermissionService.identifiant(role))
        permission = PermissionRepository.get_actif_by_id(RolePermissionService.identifiant(permission))
        if not role:
            raise ValidationError("Rôle introuvable ou inactif.")
        if not permission:
            raise ValidationError("Permission introuvable ou inactive.")
        if role.est_systeme and attribue_par is not None:
            raise ValidationError("Les permissions d’un rôle système sont gérées uniquement par le seed.")
        if attribue_par is not None and not getattr(attribue_par, "is_superuser", False):
            CreationSubordonneeService.verifier_permission_attribuable(attribue_par, permission)
        if RolePermissionRepository.permission_deja_associee(role, permission):
            raise ValidationError("Cette permission est déjà associée à ce rôle.")

        lien = RolePermission(
            role=role,
            permission=permission,
            est_delegable=est_delegable,
            perimetre_delegation_max=perimetre_delegation_max,
            statut=RolePermission.Statut.ACTIVE,
        )
        lien.full_clean()
        lien.save()
        return lien

    @staticmethod
    @transaction.atomic
    def retirer_permission(role_permission):
        lien = RolePermission.objects.select_for_update().filter(
            id=RolePermissionService.identifiant(role_permission),
            deleted_at__isnull=True,
        ).first()
        if not lien:
            raise ValidationError("Lien rôle-permission introuvable.")

        lien.statut = RolePermission.Statut.RETIREE
        lien.deleted_at = RolePermissionService.maintenant()
        lien.save(update_fields=["statut", "deleted_at", "updated_at"])
        return lien


class AffectationActeurService(ServiceBase):
    """Gestion métier des affectations d'acteurs."""

    PERMISSION_AFFECTER_ACTEUR = "affecter_acteur_session"

    @staticmethod
    @transaction.atomic
    def creer_affectation(
        *,
        acteur,
        niveau_affectation,
        session=None,
        region_code="",
        centre_id=None,
        date_debut=None,
        date_fin=None,
        affecte_par=None,
    ):
        acteur = ActeurRepository.get_actif_by_id(AffectationActeurService.identifiant(acteur))
        if not acteur:
            raise ValidationError("Acteur introuvable ou inactif.")

        region_code = AffectationActeurService.normaliser_texte(region_code)
        session_id = getattr(session, "id", session) if session is not None else None

        if affecte_par is not None and not getattr(affecte_par, "is_superuser", False):
            source = CreationSubordonneeService.affectation_source(affecte_par)
            CreationSubordonneeService.verifier_perimetre(
                source, niveau=niveau_affectation, session_id=session_id,
                region_code=region_code or None, centre_id=centre_id,
            )

        affectation = AffectationActeur(
            acteur=acteur,
            session=session,
            niveau_affectation=niveau_affectation,
            region_code=region_code,
            centre_id=centre_id,
            date_debut=date_debut or AffectationActeurService.aujourd_hui(),
            date_fin=date_fin,
            statut=AffectationActeur.Statut.ACTIVE,
            affecte_par=affecte_par,
        )
        affectation.full_clean()
        affectation.save()

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(acteur.id)
        return affectation

    @staticmethod
    @transaction.atomic
    def suspendre_affectation(affectation):
        affectation = AffectationActeur.objects.select_for_update().filter(
            id=AffectationActeurService.identifiant(affectation),
            deleted_at__isnull=True,
        ).first()
        if not affectation:
            raise ValidationError("Affectation introuvable.")
        if affectation.statut != AffectationActeur.Statut.ACTIVE:
            raise ValidationError("Seule une affectation active peut être suspendue.")

        affectation.statut = AffectationActeur.Statut.SUSPENDUE
        affectation.save(update_fields=["statut", "updated_at"])

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(affectation.acteur_id)
        return affectation

    @staticmethod
    @transaction.atomic
    def reactiver_affectation(affectation):
        affectation = AffectationActeur.objects.select_for_update().filter(
            id=AffectationActeurService.identifiant(affectation),
            deleted_at__isnull=True,
        ).first()
        if not affectation:
            raise ValidationError("Affectation introuvable.")
        if affectation.statut != AffectationActeur.Statut.SUSPENDUE:
            raise ValidationError("Seule une affectation suspendue peut être réactivée.")

        affectation.statut = AffectationActeur.Statut.ACTIVE
        affectation.save(update_fields=["statut", "updated_at"])

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(affectation.acteur_id)
        return affectation

    @staticmethod
    @transaction.atomic
    def terminer_affectation(affectation):
        affectation = AffectationActeur.objects.select_for_update().filter(
            id=AffectationActeurService.identifiant(affectation),
            deleted_at__isnull=True,
        ).first()
        if not affectation:
            raise ValidationError("Affectation introuvable.")

        affectation.statut = AffectationActeur.Statut.TERMINEE
        affectation.date_fin = affectation.date_fin or AffectationActeurService.aujourd_hui()
        affectation.save(update_fields=["statut", "date_fin", "updated_at"])

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(affectation.acteur_id)
        return affectation


class AffectationRoleService(ServiceBase):
    """Attribution des rôles dans une affectation."""

    @staticmethod
    @transaction.atomic
    def attribuer_role(affectation, role, *, attribue_par=None, date_attribution=None, date_expiration=None):
        affectation = AffectationActeurRepository.get_active_by_id(AffectationRoleService.identifiant(affectation))
        role = RoleRepository.get_actif_by_id(AffectationRoleService.identifiant(role))
        if not affectation:
            raise ValidationError("Affectation introuvable ou inactive.")
        if not role:
            raise ValidationError("Rôle introuvable ou inactif.")
        if AffectationRoleRepository.role_deja_attribue(affectation, role):
            raise ValidationError("Ce rôle est déjà attribué à cette affectation.")

        rangs_perimetres = {
            Role.Perimetre.CENTRE: 1,
            Role.Perimetre.REGION: 2,
            Role.Perimetre.NATIONAL: 3,
            Role.Perimetre.PLATEFORME: 4,
        }

        rang_role = rangs_perimetres.get(role.perimetre_autorise, 0)
        rang_affectation = rangs_perimetres.get(affectation.niveau_affectation, 0)

        if rang_role > rang_affectation:
            raise ValidationError(
                "Le rôle possède un périmètre plus large que l'affectation."
            )

        if attribue_par is not None and not getattr(attribue_par, "is_superuser", False):
            affectation_source_id = obtenir_affectation_courante_id()
            affectation_source = None
            if affectation_source_id not in (None, -1):
                affectation_source = AffectationActeurRepository.get_active_by_id(affectation_source_id)
            if affectation_source is None or affectation_source.acteur_id != attribue_par.id:
                raise ValidationError(
                    "Choisissez une affectation de travail valide avant d'attribuer un rôle."
                )

            niveaux_source = list(
                AffectationRole.objects.filter(
                    affectation_acteur=affectation_source,
                    statut=AffectationRole.Statut.ACTIF,
                    deleted_at__isnull=True,
                ).values_list("role__niveau", flat=True)
            )
            if not niveaux_source or role.niveau < min(niveaux_source):
                raise ValidationError(
                    "Vous ne pouvez ajouter qu'un rôle de niveau égal ou inférieur au vôtre."
                )

        attribution = AffectationRole(
            affectation_acteur=affectation,
            role=role,
            date_attribution=date_attribution or AffectationRoleService.aujourd_hui(),
            date_expiration=date_expiration,
            statut=AffectationRole.Statut.ACTIF,
            attribue_par=attribue_par,
        )
        attribution.full_clean()
        attribution.save()

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(affectation.acteur_id)
        return attribution

    @staticmethod
    @transaction.atomic
    def retirer_role(affectation_role):
        attribution = AffectationRole.objects.select_for_update().filter(
            id=AffectationRoleService.identifiant(affectation_role),
            deleted_at__isnull=True,
        ).first()
        if not attribution:
            raise ValidationError("Attribution de rôle introuvable.")

        attribution.statut = AffectationRole.Statut.RETIRE
        attribution.deleted_at = AffectationRoleService.maintenant()
        attribution.save(update_fields=["statut", "deleted_at", "updated_at"])

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(attribution.affectation_acteur.acteur_id)
        return attribution


class AffectationPermissionService(ServiceBase):
    """Attribution des permissions directes exceptionnelles."""

    @staticmethod
    @transaction.atomic
    def attribuer_permission_directe(
        affectation,
        permission,
        *,
        attribue_par=None,
        date_attribution=None,
        date_expiration=None,
        est_delegable=False,
        motif="",
    ):
        affectation = AffectationActeurRepository.get_active_by_id(AffectationPermissionService.identifiant(affectation))
        permission = PermissionRepository.get_actif_by_id(AffectationPermissionService.identifiant(permission))
        if not affectation:
            raise ValidationError("Affectation introuvable ou inactive.")
        if not permission:
            raise ValidationError("Permission introuvable ou inactive.")
        if AffectationPermissionRepository.permission_deja_attribuee(affectation, permission):
            raise ValidationError("Cette permission directe est déjà attribuée à cette affectation.")

        motif_normalise = AffectationPermissionService.normaliser_texte(motif)
        if not motif_normalise:
            raise ValidationError("Le motif est obligatoire pour une permission directe.")

        attribution = AffectationPermission(
            affectation_acteur=affectation,
            permission=permission,
            date_attribution=date_attribution or AffectationPermissionService.aujourd_hui(),
            date_expiration=date_expiration,
            est_delegable=est_delegable,
            motif=motif_normalise,
            statut=AffectationPermission.Statut.ACTIVE,
            attribue_par=attribue_par,
        )
        attribution.full_clean()
        attribution.save()

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(affectation.acteur_id)
        return attribution

    @staticmethod
    @transaction.atomic
    def retirer_permission_directe(affectation_permission):
        attribution = AffectationPermission.objects.select_for_update().filter(
            id=AffectationPermissionService.identifiant(affectation_permission),
            deleted_at__isnull=True,
        ).first()
        if not attribution:
            raise ValidationError("Permission directe introuvable.")

        attribution.statut = AffectationPermission.Statut.RETIREE
        attribution.deleted_at = AffectationPermissionService.maintenant()
        attribution.save(update_fields=["statut", "deleted_at", "updated_at"])

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(attribution.affectation_acteur.acteur_id)
        return attribution


class DemandePermissionService(ServiceBase):
    """Cycle de demande, approbation et refus de permissions."""

    @staticmethod
    @transaction.atomic
    def soumettre_demande(*, acteur, permission, justification, affectation=None):
        acteur = ActeurRepository.get_actif_by_id(DemandePermissionService.identifiant(acteur))
        permission = PermissionRepository.get_actif_by_id(DemandePermissionService.identifiant(permission))
        if not acteur:
            raise ValidationError("Acteur introuvable ou inactif.")
        if not permission:
            raise ValidationError("Permission introuvable ou inactive.")
        if DemandePermissionRepository.demande_en_attente_existe(acteur, permission, affectation):
            raise ValidationError("Une demande identique est déjà en attente.")

        demande = DemandePermission(
            acteur=acteur,
            affectation_acteur=affectation,
            permission=permission,
            justification=DemandePermissionService.normaliser_texte(justification),
            statut=DemandePermission.Statut.EN_ATTENTE,
        )
        demande.full_clean()
        demande.save()
        return demande

    @staticmethod
    @transaction.atomic
    def approuver_demande(demande, *, decideur, motif_decision="", date_expiration=None):
        demande = DemandePermission.objects.select_for_update().filter(
            id=DemandePermissionService.identifiant(demande),
            deleted_at__isnull=True,
        ).first()
        if not demande or demande.statut != DemandePermission.Statut.EN_ATTENTE:
            raise ValidationError("Demande introuvable ou non traitable.")

        demande.statut = DemandePermission.Statut.APPROUVEE
        demande.decideur = decideur
        demande.date_decision = DemandePermissionService.maintenant()
        demande.motif_decision = DemandePermissionService.normaliser_texte(motif_decision)
        demande.save()

        if demande.affectation_acteur_id:
            AffectationPermissionService.attribuer_permission_directe(
                demande.affectation_acteur,
                demande.permission,
                attribue_par=decideur,
                date_expiration=date_expiration,
                motif=f"Demande approuvée #{demande.id}",
            )

        return demande

    @staticmethod
    @transaction.atomic
    def refuser_demande(demande, *, decideur, motif_decision=""):
        demande = DemandePermission.objects.select_for_update().filter(
            id=DemandePermissionService.identifiant(demande),
            deleted_at__isnull=True,
        ).first()
        if not demande or demande.statut != DemandePermission.Statut.EN_ATTENTE:
            raise ValidationError("Demande introuvable ou non traitable.")

        demande.statut = DemandePermission.Statut.REFUSEE
        demande.decideur = decideur
        demande.date_decision = DemandePermissionService.maintenant()
        demande.motif_decision = DemandePermissionService.normaliser_texte(motif_decision)
        demande.save()
        return demande


class DelegationActeurService(ServiceBase):
    """Gestion des délégations temporaires."""

    @staticmethod
    @transaction.atomic
    def creer_delegation(
        *,
        acteur_source,
        acteur_cible,
        affectation_acteur,
        type_delegation,
        date_fin,
        role=None,
        permission=None,
        motif="",
        date_debut=None,
    ):
        acteur_source = ActeurRepository.get_actif_by_id(DelegationActeurService.identifiant(acteur_source))
        acteur_cible = ActeurRepository.get_actif_by_id(DelegationActeurService.identifiant(acteur_cible))
        affectation = AffectationActeurRepository.get_active_by_id(DelegationActeurService.identifiant(affectation_acteur))
        if not acteur_source or not acteur_cible:
            raise ValidationError("Acteur source ou cible introuvable/inactif.")
        if not affectation:
            raise ValidationError("Affectation introuvable ou inactive.")
        if acteur_source.id == acteur_cible.id:
            raise ValidationError("Un acteur ne peut pas se déléguer à lui-même.")
        if DelegationActeurRepository.delegation_active_existe(acteur_source, acteur_cible, affectation):
            raise ValidationError("Une délégation active existe déjà entre ces deux acteurs pour cette affectation.")

        delegation = DelegationActeur(
            acteur_source=acteur_source,
            acteur_cible=acteur_cible,
            affectation_acteur=affectation,
            role=role,
            permission=permission,
            type_delegation=type_delegation,
            date_debut=date_debut or DelegationActeurService.aujourd_hui(),
            date_fin=date_fin,
            motif=DelegationActeurService.normaliser_texte(motif),
            statut=DelegationActeur.Statut.ACTIVE,
        )
        delegation.full_clean()
        delegation.save()

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(acteur_cible.id)
        return delegation

    @staticmethod
    @transaction.atomic
    def terminer_delegation(delegation):
        delegation = DelegationActeur.objects.select_for_update().filter(
            id=DelegationActeurService.identifiant(delegation),
            deleted_at__isnull=True,
        ).first()
        if not delegation:
            raise ValidationError("Délégation introuvable.")

        delegation.statut = DelegationActeur.Statut.TERMINEE
        delegation.save(update_fields=["statut", "updated_at"])

        ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit(delegation.acteur_cible_id)
        return delegation


class ControleAccesService(ServiceBase):
    """Contrôle central des permissions et périmètres accounts.

    Certaines permissions d'action supposent l'accès à une interface mère.
    Les permissions de lecture nécessaires sont donc ajoutées uniquement au
    calcul des permissions effectives. Elles ne sont pas enregistrées dans les
    rôles, permissions directes ou délégations.
    """

    REGLES_PERMISSIONS_IMPLICITES = (
        # Imports officiels : creer_import_officiel est la permission maîtresse.
        # Elle donne accès à tout le parcours d'import, sans dupliquer ces
        # associations dans les rôles enregistrés en base.
        (
            {"creer_import_officiel"},
            {
                "lister_imports_officiels",
                "consulter_import_officiel",
                "modifier_import_officiel",
                "supprimer_import_officiel",
                "consulter_champs_attendus_import",
                "consulter_progression_import",
                "relancer_lecture_import",
                "valider_correspondance_import",
                "valider_lignes_import",
                "confirmer_import_officiel",
                "annuler_import_officiel",
                "consulter_correspondances_import",
                "consulter_lignes_import",
                "corriger_ligne_import",
                "ignorer_ligne_import",
                "consulter_erreurs_import",
            },
        ),
        # Toute action portant sur un import existant ouvre sa liste et sa fiche.
        (
            {
                "modifier_import_officiel",
                "supprimer_import_officiel",
                "consulter_progression_import",
                "relancer_lecture_import",
                "valider_correspondance_import",
                "valider_lignes_import",
                "confirmer_import_officiel",
                "annuler_import_officiel",
                "consulter_correspondances_import",
                "consulter_lignes_import",
                "corriger_ligne_import",
                "ignorer_ligne_import",
                "consulter_erreurs_import",
            },
            {"lister_imports_officiels", "consulter_import_officiel"},
        ),
        # Correspondance : l'opérateur doit voir les colonnes et les champs attendus.
        (
            {"valider_correspondance_import"},
            {"consulter_correspondances_import", "consulter_champs_attendus_import"},
        ),
        # Validation/correction : l'opérateur doit voir les lignes et leurs erreurs.
        (
            {
                "valider_lignes_import",
                "corriger_ligne_import",
                "ignorer_ligne_import",
                "confirmer_import_officiel",
            },
            {"consulter_lignes_import", "consulter_erreurs_import"},
        ),
        # Relance et confirmation nécessitent le suivi de progression.
        (
            {"relancer_lecture_import", "confirmer_import_officiel"},
            {"consulter_progression_import"},
        ),
        # Gestion des sessions : les actions ouvrent l'interface principale.
        (
            {
                "creer_session", "modifier_session", "cloturer_session",
                "archiver_session", "configurer_parametres_session",
                "modifier_parametres_session", "consulter_historique_sessions",
                "consulter_historique_parametres_session",
            },
            {"lister_sessions"},
        ),
        # Toute action sur une session existante nécessite sa fiche.
        (
            {
                "modifier_session", "cloturer_session", "archiver_session",
                "configurer_parametres_session", "modifier_parametres_session",
                "consulter_historique_sessions",
                "consulter_historique_parametres_session",
            },
            {"consulter_session"},
        ),
        # Gestion des acteurs : toute action du groupe ouvre la liste.
        (
            {
                "creer_acteur",
                "modifier_acteur",
                "desactiver_acteur",
                "reactiver_acteur",
                "consulter_acteur",
                "lister_acteurs",
            },
            {"lister_acteurs"},
        ),
        # Les actions qui portent sur un acteur nécessitent aussi sa fiche.
        (
            {
                "modifier_acteur",
                "desactiver_acteur",
                "reactiver_acteur",
            },
            {"consulter_acteur"},
        ),
        # Gestion des affectations : toute action ouvre la liste et le détail.
        (
            {
                "lister_affectations_acteurs",
                "consulter_affectation_acteur",
                "affecter_acteur_session",
                "retirer_affectation_acteur",
                "suspendre_affectation_acteur",
                "reactiver_affectation_acteur",
                "attribuer_role",
                "retirer_role",
                "attribuer_permission_directe",
                "retirer_permission_directe",
            },
            {"lister_affectations_acteurs", "consulter_affectation_acteur"},
        ),
        # Gestion des rôles : toute action du groupe ouvre la liste.
        (
            {
                "creer_role",
                "modifier_role",
                "desactiver_role",
                "consulter_role",
                "lister_roles",
                "ajouter_permission_role",
                "retirer_permission_role",
            },
            {"lister_roles"},
        ),
        # Modifier un rôle ou ses permissions nécessite son détail.
        (
            {
                "modifier_role",
                "desactiver_role",
                "ajouter_permission_role",
                "retirer_permission_role",
            },
            {"consulter_role"},
        ),
        # Gestion des permissions : toute action du groupe ouvre le catalogue.
        (
            {
                "consulter_permission",
                "lister_permissions",
                "ajouter_permission_role",
                "retirer_permission_role",
                "attribuer_permission_directe",
                "retirer_permission_directe",
                "demander_permission",
                "lister_demandes_permissions",
                "consulter_demande_permission",
                "approuver_demande_permission",
                "refuser_demande_permission",
                "annuler_demande_permission",
            },
            {"lister_permissions"},
        ),
        # Toute action sur une demande ouvre la liste des demandes.
        (
            {
                "demander_permission",
                "lister_demandes_permissions",
                "consulter_demande_permission",
                "approuver_demande_permission",
                "refuser_demande_permission",
                "annuler_demande_permission",
            },
            {"lister_demandes_permissions"},
        ),
        # Décider ou annuler une demande nécessite son détail.
        (
            {
                "approuver_demande_permission",
                "refuser_demande_permission",
                "annuler_demande_permission",
            },
            {"consulter_demande_permission"},
        ),
        # Affectations territoriales : régions, centres et parcours d'affectation.
        # Ces accès sont calculés uniquement dans les permissions effectives.
        # Aucune association supplémentaire n'est créée en base.
        (
            {
                "creer_region",
                "modifier_region",
                "desactiver_region",
                "consulter_region",
            },
            {"lister_regions"},
        ),
        (
            {
                "modifier_region",
                "desactiver_region",
            },
            {"consulter_region"},
        ),
        (
            {
                "creer_centre",
                "modifier_centre",
                "desactiver_centre",
                "mettre_centre_maintenance",
                "reactiver_centre",
                "verifier_capacite_centre",
                "consulter_centre",
            },
            {"lister_centres"},
        ),
        (
            {
                "modifier_centre",
                "desactiver_centre",
                "mettre_centre_maintenance",
                "reactiver_centre",
                "verifier_capacite_centre",
            },
            {"consulter_centre"},
        ),
        (
            {
                "proposer_affectation_regionale",
                "affecter_region",
                "modifier_affectation_regionale",
                "valider_affectation_regionale",
                "annuler_affectation_regionale",
            },
            {
                "consulter_affectations_regionales",
                "lister_regions",
            },
        ),
        (
            {
                "proposer_affectation_centre",
                "affecter_centre",
                "modifier_affectation_centre",
                "valider_affectation_centre",
                "annuler_affectation_centre",
                "verifier_compatibilite_centre",
            },
            {
                "consulter_affectations_centres",
                "consulter_affectations_regionales",
                "lister_centres",
            },
        ),
        # Organisation interne : règles, sections, groupes et hébergement.
        (
            {
                "configurer_regles_centre",
                "modifier_regles_centre",
                "generer_sections_groupes",
                "valider_organisation_interne",
                "marquer_centre_pret_publication",
                "creer_section",
                "modifier_section",
                "supprimer_section",
                "creer_groupe",
                "modifier_groupe",
                "supprimer_groupe",
                "affecter_immerge_groupe",
                "retirer_immerge_groupe",
            },
            {
                "consulter_regles_centre",
                "lister_centres",
            },
        ),
        (
            {
                "affecter_immerge_groupe",
                "retirer_immerge_groupe",
            },
            {"consulter_affectations_centres"},
        ),
        (
            {
                "creer_dortoir",
                "modifier_dortoir",
                "desactiver_dortoir",
                "mettre_dortoir_hors_service",
                "creer_lit",
                "modifier_lit",
                "mettre_lit_hors_service",
                "reactiver_lit",
                "proposer_attribution_lit",
                "attribuer_lit",
                "modifier_attribution_lit",
                "liberer_lit",
            },
            {
                "consulter_hebergement",
                "lister_centres",
            },
        ),
        (
            {
                "proposer_attribution_lit",
                "attribuer_lit",
                "modifier_attribution_lit",
                "liberer_lit",
            },
            {"consulter_affectations_centres"},
        ),
        # Kits : les actions ouvrent aussi les écrans qui les portent.
        (
            {
                "creer_article_kit_a_remettre",
                "creer_article_kit_a_apporter",
                "modifier_article_kit",
                "desactiver_article_kit",
                "reactiver_article_kit",
                "supprimer_article_kit",
            },
            {"consulter_articles_kit"},
        ),
        (
            {
                "enregistrer_remise_kit",
                "annuler_remise_kit",
                "consulter_statistiques_kits",
                "preparer_remises_kit_masse",
                "valider_remises_kit_masse",
                "annuler_remises_kit_masse",
            },
            {"consulter_remises_kit"},
        ),
        (
            {
                "preparer_remises_kit_masse",
                "valider_remises_kit_masse",
                "annuler_remises_kit_masse",
            },
            {"consulter_progression_kits"},
        ),
        # Inscriptions volontaires : toute action interne ouvre la liste.
        (
            {
                "lister_inscriptions_volontaires",
                "consulter_inscription_volontaire",
                "accepter_inscription_volontaire",
                "refuser_inscription_volontaire",
                "accepter_inscriptions_volontaires_lot",
            },
            {"lister_inscriptions_volontaires"},
        ),
        # Une décision individuelle nécessite le détail de la demande.
        (
            {
                "accepter_inscription_volontaire",
                "refuser_inscription_volontaire",
                "accepter_inscriptions_volontaires_lot",
            },
            {"consulter_inscription_volontaire"},
        ),
        # L'acceptation en lot réutilise le droit d'acceptation individuelle.
        (
            {"accepter_inscriptions_volontaires_lot"},
            {"accepter_inscription_volontaire"},
        ),
    )

    @classmethod
    def ajouter_permissions_implicites(cls, codes_permissions):
        """Retourne les permissions enrichies des accès de navigation requis.

        La fermeture est répétée jusqu'à stabilité afin qu'une permission
        implicite puisse elle-même ouvrir l'interface mère d'un autre groupe.
        """
        permissions = set(codes_permissions or ())
        modifie = True
        while modifie:
            modifie = False
            for permissions_declencheuses, permissions_ajoutees in cls.REGLES_PERMISSIONS_IMPLICITES:
                if permissions.intersection(permissions_declencheuses):
                    nouvelles = permissions_ajoutees - permissions
                    if nouvelles:
                        permissions.update(nouvelles)
                        modifie = True
        return permissions

    @staticmethod
    def permissions_effectives(acteur, affectation):
        acteur = ActeurRepository.get_actif_by_id(ControleAccesService.identifiant(acteur))
        affectation = AffectationActeurRepository.get_active_by_id(ControleAccesService.identifiant(affectation))
        if not acteur or not affectation or affectation.acteur_id != acteur.id:
            return set()
        permissions = ControleAccesRepository.get_permission_codes_acteur(acteur, affectation)
        return ControleAccesService.ajouter_permissions_implicites(permissions)

    @staticmethod
    def acteur_peut(acteur, code_permission, *, affectation=None, session_id=None, region_code=None, centre_id=None):
        acteur = ActeurRepository.get_actif_by_id(ControleAccesService.identifiant(acteur))
        if not acteur:
            return ResultatControleAcces(False, "Acteur introuvable ou inactif.")

        affectations = AffectationActeurRepository.lister_actives_par_acteur(acteur)

        # Une requête API doit rester dans le contexte choisi par l'acteur.
        # Si aucun contexte n'est transmis et que l'acteur n'a qu'une seule
        # affectation active, celle-ci peut être utilisée sans ambiguïté.
        if affectation is None:
            affectation_contexte_id = obtenir_affectation_courante_id()
            if affectation_contexte_id == -1:
                return ResultatControleAcces(False, "Identifiant d'affectation courante invalide.")
            if affectation_contexte_id is not None:
                affectation = affectation_contexte_id
            elif affectations.count() > 1:
                return ResultatControleAcces(
                    False,
                    "Choisissez une affectation de travail avant d'effectuer cette action.",
                )

        if affectation is not None:
            affectations = affectations.filter(id=ControleAccesService.identifiant(affectation))

        for affectation_active in affectations:
            if not ControleAccesService.affectation_couvre_perimetre(
                affectation_active,
                session_id=session_id,
                region_code=region_code,
                centre_id=centre_id,
            ):
                continue

            permissions = ControleAccesService.permissions_effectives(acteur, affectation_active)
            if code_permission in permissions:
                return ResultatControleAcces(True, affectation=affectation_active)

        return ResultatControleAcces(False, "Permission absente ou hors périmètre.")

    @staticmethod
    def affectation_couvre_perimetre(affectation, *, session_id=None, region_code=None, centre_id=None):
        """Vérifie si une affectation active couvre le périmètre demandé.

        La session n'est pas un périmètre. Elle limite seulement une affectation
        lorsqu'elle est renseignée. Une affectation liée à une session ne couvre
        que les actions demandées pour cette même session. Une affectation sans
        session reste permanente tant que son statut et ses dates sont actifs.
        """
        niveau = affectation.niveau_affectation

        try:
            session_id = int(session_id) if session_id is not None else None
        except (TypeError, ValueError):
            return False

        try:
            centre_id = int(centre_id) if centre_id is not None else None
        except (TypeError, ValueError):
            return False

        if affectation.session_id is not None:
            if session_id is None or affectation.session_id != session_id:
                return False

        if niveau == AffectationActeur.NiveauAffectation.PLATEFORME:
            return True

        if niveau == AffectationActeur.NiveauAffectation.NATIONAL:
            return True

        if niveau == AffectationActeur.NiveauAffectation.REGION:
            return bool(region_code and affectation.region_code.lower() == str(region_code).lower())

        if niveau == AffectationActeur.NiveauAffectation.CENTRE:
            return centre_id is not None and affectation.centre_id == centre_id

        return False


class ContexteActeurService(ServiceBase):
    """Construit le contexte de travail personnel d'un acteur connecté."""

    PRIORITE_NIVEAU = {
        AffectationActeur.NiveauAffectation.PLATEFORME: 0,
        AffectationActeur.NiveauAffectation.NATIONAL: 1,
        AffectationActeur.NiveauAffectation.REGION: 2,
        AffectationActeur.NiveauAffectation.CENTRE: 3,
    }

    @staticmethod
    def lister_affectations_actives(acteur):
        acteur = ActeurRepository.get_actif_by_id(ContexteActeurService.identifiant(acteur))
        if not acteur:
            raise ValidationError("Acteur introuvable ou inactif.")
        return AffectationActeurRepository.lister_actives_par_acteur(acteur)

    @staticmethod
    def selectionner_affectation_par_defaut(acteur):
        """Priorise une affectation permanente, puis le périmètre le plus large."""

        affectations = list(ContexteActeurService.lister_affectations_actives(acteur))
        if not affectations:
            return None

        def cle(affectation):
            est_temporaire = 1 if affectation.session_id is not None else 0
            priorite_niveau = ContexteActeurService.PRIORITE_NIVEAU.get(
                affectation.niveau_affectation,
                99,
            )
            date_debut = affectation.date_debut.toordinal() if affectation.date_debut else 0
            return (est_temporaire, priorite_niveau, -date_debut, -affectation.id)

        return sorted(affectations, key=cle)[0]

    @staticmethod
    def _roles_affectation(affectation):
        attributions = AffectationRoleRepository.lister_actifs_par_affectation(affectation)
        return [
            {
                "id": attribution.role_id,
                "code": attribution.role.code,
                "libelle": attribution.role.libelle,
                "niveau": attribution.role.niveau,
                "perimetre_autorise": attribution.role.perimetre_autorise,
            }
            for attribution in attributions.order_by("role__niveau", "role__code")
        ]

    @staticmethod
    def _session_affectation(affectation):
        if not affectation.session_id:
            return None
        return {
            "id": affectation.session_id,
            "code": affectation.session.code,
            "nom": affectation.session.nom,
            "statut": affectation.session.statut,
            "date_debut": affectation.session.date_debut,
            "date_fin": affectation.session.date_fin,
        }

    @staticmethod
    def serialiser_affectation(acteur, affectation, *, est_par_defaut=False):
        from affectations.models import CentreImmersion, RegionImmersion

        permissions = sorted(ControleAccesService.permissions_effectives(acteur, affectation))
        region_code = affectation.region_code or ""
        region_nom = ""
        centre_nom = ""

        if region_code:
            region_nom = (
                RegionImmersion.objects.filter(
                    code__iexact=region_code,
                    deleted_at__isnull=True,
                )
                .values_list("nom", flat=True)
                .first()
                or region_code
            )

        if affectation.centre_id:
            centre_nom = (
                CentreImmersion.objects.filter(
                    id=affectation.centre_id,
                    deleted_at__isnull=True,
                )
                .values_list("nom", flat=True)
                .first()
                or f"Centre {affectation.centre_id}"
            )

        return {
            "id": affectation.id,
            "est_permanente": affectation.session_id is None,
            "est_par_defaut": est_par_defaut,
            "niveau_affectation": affectation.niveau_affectation,
            "region_code": region_code,
            "region_nom": region_nom,
            "centre_id": affectation.centre_id,
            "centre_nom": centre_nom,
            "date_debut": affectation.date_debut,
            "date_fin": affectation.date_fin,
            "statut": affectation.statut,
            "session": ContexteActeurService._session_affectation(affectation),
            "roles": ContexteActeurService._roles_affectation(affectation),
            "permissions": permissions,
        }

    @staticmethod
    def construire_contexte(acteur, affectation=None):
        acteur = ActeurRepository.get_actif_by_id(ContexteActeurService.identifiant(acteur))
        if not acteur:
            raise ValidationError("Acteur introuvable ou inactif.")

        affectations = ContexteActeurService.lister_affectations_actives(acteur)
        nombre_affectations = affectations.count()
        affectation_par_defaut = ContexteActeurService.selectionner_affectation_par_defaut(acteur)

        if affectation is None:
            affectation_courante = affectation_par_defaut
        else:
            affectation_courante = AffectationActeurRepository.get_active_by_id(
                ContexteActeurService.identifiant(affectation)
            )
            if not affectation_courante or affectation_courante.acteur_id != acteur.id:
                raise ValidationError("Cette affectation active ne vous appartient pas.")

        return {
            "acteur": acteur,
            "affectation_courante": (
                ContexteActeurService.serialiser_affectation(
                    acteur,
                    affectation_courante,
                    est_par_defaut=(
                        affectation_par_defaut is not None
                        and affectation_courante.id == affectation_par_defaut.id
                    ),
                )
                if affectation_courante
                else None
            ),
            "nombre_affectations_actives": nombre_affectations,
            "peut_changer_affectation": nombre_affectations > 1,
        }

    @staticmethod
    def construire_liste_affectations(acteur):
        acteur = ActeurRepository.get_actif_by_id(ContexteActeurService.identifiant(acteur))
        if not acteur:
            raise ValidationError("Acteur introuvable ou inactif.")

        affectations = list(ContexteActeurService.lister_affectations_actives(acteur))
        affectation_par_defaut = ContexteActeurService.selectionner_affectation_par_defaut(acteur)
        affectation_par_defaut_id = getattr(affectation_par_defaut, "id", None)

        return {
            "affectation_par_defaut_id": affectation_par_defaut_id,
            "nombre_affectations_actives": len(affectations),
            "affectations": [
                ContexteActeurService.serialiser_affectation(
                    acteur,
                    affectation,
                    est_par_defaut=affectation.id == affectation_par_defaut_id,
                )
                for affectation in affectations
            ],
        }
