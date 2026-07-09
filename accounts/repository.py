from django.db.models import Q
from django.utils import timezone

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


class BaseRepository:
    """Méthodes communes aux repositories FasoIM."""

    @staticmethod
    def non_supprimes(queryset):
        return queryset.filter(deleted_at__isnull=True)

    @staticmethod
    def normaliser_texte(valeur):
        if valeur is None:
            return ""
        return str(valeur).strip()

    @staticmethod
    def identifiant(objet_ou_id):
        return getattr(objet_ou_id, "id", objet_ou_id)


class ActeurRepository(BaseRepository):
    """Requêtes liées aux acteurs internes FasoIM."""

    @staticmethod
    def queryset():
        return Acteur.objects.all()

    @staticmethod
    def non_supprimes():
        return ActeurRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actifs():
        return ActeurRepository.non_supprimes().filter(
            is_active=True,
            statut=Acteur.Statut.ACTIF,
        )

    @staticmethod
    def get_actif_by_id(acteur_id):
        return ActeurRepository.actifs().filter(id=acteur_id).first()

    @staticmethod
    def get_any_by_id(acteur_id):
        return ActeurRepository.queryset().filter(id=acteur_id).first()

    @staticmethod
    def get_by_email(email):
        email = ActeurRepository.normaliser_texte(email)
        if not email:
            return None
        return ActeurRepository.non_supprimes().filter(email__iexact=email).first()

    @staticmethod
    def get_by_username(username):
        username = ActeurRepository.normaliser_texte(username)
        if not username:
            return None
        return ActeurRepository.non_supprimes().filter(username__iexact=username).first()

    @staticmethod
    def rechercher(terme=None, statut=None):
        queryset = ActeurRepository.non_supprimes()

        if statut:
            queryset = queryset.filter(statut=statut)

        terme = ActeurRepository.normaliser_texte(terme)
        if terme:
            queryset = queryset.filter(
                Q(username__icontains=terme)
                | Q(first_name__icontains=terme)
                | Q(last_name__icontains=terme)
                | Q(email__icontains=terme)
                | Q(telephone__icontains=terme)
            )

        return queryset.order_by("last_name", "first_name", "username")

    @staticmethod
    def email_existe(email, exclude_id=None):
        email = ActeurRepository.normaliser_texte(email)
        if not email:
            return False
        queryset = ActeurRepository.non_supprimes().filter(email__iexact=email)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    @staticmethod
    def username_existe(username, exclude_id=None):
        username = ActeurRepository.normaliser_texte(username)
        if not username:
            return False
        queryset = ActeurRepository.non_supprimes().filter(username__iexact=username)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    @staticmethod
    def telephone_existe(telephone, exclude_id=None):
        telephone = ActeurRepository.normaliser_texte(telephone)
        if not telephone:
            return False
        queryset = ActeurRepository.non_supprimes().filter(telephone=telephone)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()


class RoleRepository(BaseRepository):
    """Requêtes liées aux rôles métier."""

    @staticmethod
    def queryset():
        return Role.objects.all()

    @staticmethod
    def non_supprimes():
        return RoleRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actifs():
        return RoleRepository.non_supprimes().filter(statut=Role.Statut.ACTIF)

    @staticmethod
    def get_actif_by_id(role_id):
        return RoleRepository.actifs().filter(id=role_id).first()

    @staticmethod
    def get_by_code(code):
        code = RoleRepository.normaliser_texte(code)
        if not code:
            return None
        return RoleRepository.non_supprimes().filter(code__iexact=code).first()

    @staticmethod
    def lister_par_niveau(niveau):
        return RoleRepository.actifs().filter(niveau=niveau)

    @staticmethod
    def lister_par_perimetre(perimetre):
        return RoleRepository.actifs().filter(perimetre_autorise=perimetre)

    @staticmethod
    def lister_roles_systeme():
        return RoleRepository.actifs().filter(est_systeme=True)

    @staticmethod
    def lister_roles_modifiables():
        return RoleRepository.actifs().filter(est_modifiable=True)

    @staticmethod
    def code_existe(code, exclude_id=None):
        code = RoleRepository.normaliser_texte(code)
        if not code:
            return False
        queryset = RoleRepository.non_supprimes().filter(code__iexact=code)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()


class PermissionRepository(BaseRepository):
    """Requêtes liées au catalogue système des permissions."""

    @staticmethod
    def queryset():
        return Permission.objects.all()

    @staticmethod
    def non_supprimes():
        return PermissionRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actives():
        return PermissionRepository.non_supprimes().filter(statut=Permission.Statut.ACTIVE)

    @staticmethod
    def get_actif_by_id(permission_id):
        return PermissionRepository.actives().filter(id=permission_id).first()

    @staticmethod
    def get_by_code(code):
        code = PermissionRepository.normaliser_texte(code)
        if not code:
            return None
        return PermissionRepository.non_supprimes().filter(code__iexact=code).first()

    @staticmethod
    def get_by_codes(codes):
        codes = [PermissionRepository.normaliser_texte(code) for code in codes or []]
        codes = [code for code in codes if code]
        return PermissionRepository.actives().filter(code__in=codes)

    @staticmethod
    def lister_par_module(module):
        module = PermissionRepository.normaliser_texte(module)
        queryset = PermissionRepository.actives()
        if module:
            queryset = queryset.filter(module__iexact=module)
        return queryset.order_by("module", "code")

    @staticmethod
    def code_existe(code, exclude_id=None):
        code = PermissionRepository.normaliser_texte(code)
        if not code:
            return False
        queryset = PermissionRepository.non_supprimes().filter(code__iexact=code)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()


class RolePermissionRepository(BaseRepository):
    """Requêtes de liaison entre rôles et permissions."""

    @staticmethod
    def queryset():
        return RolePermission.objects.select_related("role", "permission")

    @staticmethod
    def non_supprimes():
        return RolePermissionRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actives():
        return RolePermissionRepository.non_supprimes().filter(
            statut=RolePermission.Statut.ACTIVE,
            role__deleted_at__isnull=True,
            role__statut=Role.Statut.ACTIF,
            permission__deleted_at__isnull=True,
            permission__statut=Permission.Statut.ACTIVE,
        )

    @staticmethod
    def lister_par_role(role):
        role_id = RolePermissionRepository.identifiant(role)
        return RolePermissionRepository.actives().filter(role_id=role_id)

    @staticmethod
    def lister_permissions_codes_par_role(role):
        return RolePermissionRepository.lister_par_role(role).values_list(
            "permission__code",
            flat=True,
        ).distinct()

    @staticmethod
    def lister_delegables_par_role(role):
        return RolePermissionRepository.lister_par_role(role).filter(est_delegable=True)

    @staticmethod
    def permission_deja_associee(role, permission):
        role_id = RolePermissionRepository.identifiant(role)
        permission_id = RolePermissionRepository.identifiant(permission)
        return RolePermissionRepository.non_supprimes().filter(
            role_id=role_id,
            permission_id=permission_id,
        ).exists()


class AffectationActeurRepository(BaseRepository):
    """Requêtes liées aux périmètres d'action des acteurs."""

    @staticmethod
    def queryset():
        return AffectationActeur.objects.select_related("acteur", "affecte_par")

    @staticmethod
    def non_supprimes():
        return AffectationActeurRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actives(date_reference=None):
        date_reference = date_reference or timezone.localdate()
        return AffectationActeurRepository.non_supprimes().filter(
            statut=AffectationActeur.Statut.ACTIVE,
            date_debut__lte=date_reference,
        ).filter(
            Q(date_fin__isnull=True) | Q(date_fin__gte=date_reference)
        )

    @staticmethod
    def get_active_by_id(affectation_id, date_reference=None):
        return AffectationActeurRepository.actives(date_reference).filter(id=affectation_id).first()

    @staticmethod
    def lister_actives_par_acteur(acteur, date_reference=None):
        acteur_id = AffectationActeurRepository.identifiant(acteur)
        return AffectationActeurRepository.actives(date_reference).filter(acteur_id=acteur_id)

    @staticmethod
    def lister_ids_actives_par_acteur(acteur, date_reference=None):
        return AffectationActeurRepository.lister_actives_par_acteur(
            acteur,
            date_reference,
        ).values_list("id", flat=True)

    @staticmethod
    def lister_par_session(session_id, date_reference=None):
        return AffectationActeurRepository.actives(date_reference).filter(session_id=session_id)

    @staticmethod
    def lister_par_region(region_code, date_reference=None):
        region_code = AffectationActeurRepository.normaliser_texte(region_code)
        return AffectationActeurRepository.actives(date_reference).filter(region_code__iexact=region_code)

    @staticmethod
    def lister_par_centre(centre_id, date_reference=None):
        return AffectationActeurRepository.actives(date_reference).filter(centre_id=centre_id)

    @staticmethod
    def a_affectation_active(acteur, session_id=None, region_code=None, centre_id=None, date_reference=None):
        queryset = AffectationActeurRepository.lister_actives_par_acteur(acteur, date_reference)

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if region_code:
            queryset = queryset.filter(region_code__iexact=region_code)
        if centre_id is not None:
            queryset = queryset.filter(centre_id=centre_id)

        return queryset.exists()


class AffectationRoleRepository(BaseRepository):
    """Requêtes liées aux rôles attribués dans une affectation."""

    @staticmethod
    def queryset():
        return AffectationRole.objects.select_related(
            "affectation_acteur",
            "affectation_acteur__acteur",
            "role",
            "attribue_par",
        )

    @staticmethod
    def non_supprimes():
        return AffectationRoleRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actifs(date_reference=None):
        date_reference = date_reference or timezone.localdate()
        return AffectationRoleRepository.non_supprimes().filter(
            statut=AffectationRole.Statut.ACTIF,
            date_attribution__lte=date_reference,
            role__deleted_at__isnull=True,
            role__statut=Role.Statut.ACTIF,
        ).filter(
            Q(date_expiration__isnull=True) | Q(date_expiration__gte=date_reference)
        )

    @staticmethod
    def lister_actifs_par_affectation(affectation, date_reference=None):
        affectation_id = AffectationRoleRepository.identifiant(affectation)
        return AffectationRoleRepository.actifs(date_reference).filter(affectation_acteur_id=affectation_id)

    @staticmethod
    def lister_roles_codes_par_affectation(affectation, date_reference=None):
        return AffectationRoleRepository.lister_actifs_par_affectation(
            affectation,
            date_reference,
        ).values_list("role__code", flat=True).distinct()

    @staticmethod
    def role_deja_attribue(affectation, role):
        affectation_id = AffectationRoleRepository.identifiant(affectation)
        role_id = AffectationRoleRepository.identifiant(role)
        return AffectationRoleRepository.non_supprimes().filter(
            affectation_acteur_id=affectation_id,
            role_id=role_id,
        ).exists()


class AffectationPermissionRepository(BaseRepository):
    """Requêtes liées aux permissions directes d'une affectation."""

    @staticmethod
    def queryset():
        return AffectationPermission.objects.select_related(
            "affectation_acteur",
            "affectation_acteur__acteur",
            "permission",
            "attribue_par",
        )

    @staticmethod
    def non_supprimes():
        return AffectationPermissionRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actives(date_reference=None):
        date_reference = date_reference or timezone.localdate()
        return AffectationPermissionRepository.non_supprimes().filter(
            statut=AffectationPermission.Statut.ACTIVE,
            date_attribution__lte=date_reference,
            permission__deleted_at__isnull=True,
            permission__statut=Permission.Statut.ACTIVE,
        ).filter(
            Q(date_expiration__isnull=True) | Q(date_expiration__gte=date_reference)
        )

    @staticmethod
    def lister_actives_par_affectation(affectation, date_reference=None):
        affectation_id = AffectationPermissionRepository.identifiant(affectation)
        return AffectationPermissionRepository.actives(date_reference).filter(affectation_acteur_id=affectation_id)

    @staticmethod
    def lister_permissions_codes_par_affectation(affectation, date_reference=None):
        return AffectationPermissionRepository.lister_actives_par_affectation(
            affectation,
            date_reference,
        ).values_list("permission__code", flat=True).distinct()

    @staticmethod
    def lister_delegables_par_affectation(affectation, date_reference=None):
        return AffectationPermissionRepository.lister_actives_par_affectation(
            affectation,
            date_reference,
        ).filter(est_delegable=True)

    @staticmethod
    def permission_deja_attribuee(affectation, permission):
        affectation_id = AffectationPermissionRepository.identifiant(affectation)
        permission_id = AffectationPermissionRepository.identifiant(permission)
        return AffectationPermissionRepository.non_supprimes().filter(
            affectation_acteur_id=affectation_id,
            permission_id=permission_id,
        ).exists()


class DemandePermissionRepository(BaseRepository):
    """Requêtes liées aux demandes de permissions supplémentaires."""

    @staticmethod
    def queryset():
        return DemandePermission.objects.select_related(
            "acteur",
            "affectation_acteur",
            "permission",
            "decideur",
        )

    @staticmethod
    def non_supprimes():
        return DemandePermissionRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def get_active_by_id(demande_id):
        return DemandePermissionRepository.non_supprimes().filter(id=demande_id).first()

    @staticmethod
    def lister_par_acteur(acteur):
        acteur_id = DemandePermissionRepository.identifiant(acteur)
        return DemandePermissionRepository.non_supprimes().filter(acteur_id=acteur_id)

    @staticmethod
    def lister_par_statut(statut):
        return DemandePermissionRepository.non_supprimes().filter(statut=statut)

    @staticmethod
    def lister_en_attente():
        return DemandePermissionRepository.lister_par_statut(DemandePermission.Statut.EN_ATTENTE)

    @staticmethod
    def demande_en_attente_existe(acteur, permission, affectation=None):
        acteur_id = DemandePermissionRepository.identifiant(acteur)
        permission_id = DemandePermissionRepository.identifiant(permission)
        queryset = DemandePermissionRepository.lister_en_attente().filter(
            acteur_id=acteur_id,
            permission_id=permission_id,
        )

        if affectation is None:
            queryset = queryset.filter(affectation_acteur__isnull=True)
        else:
            queryset = queryset.filter(affectation_acteur_id=DemandePermissionRepository.identifiant(affectation))

        return queryset.exists()


class DelegationActeurRepository(BaseRepository):
    """Requêtes liées aux délégations temporaires."""

    @staticmethod
    def queryset():
        return DelegationActeur.objects.select_related(
            "acteur_source",
            "acteur_cible",
            "affectation_acteur",
            "role",
            "permission",
        )

    @staticmethod
    def non_supprimes():
        return DelegationActeurRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actives(date_reference=None):
        date_reference = date_reference or timezone.localdate()
        return DelegationActeurRepository.non_supprimes().filter(
            statut=DelegationActeur.Statut.ACTIVE,
            date_debut__lte=date_reference,
            date_fin__gte=date_reference,
        )

    @staticmethod
    def lister_actives_recues(acteur, date_reference=None):
        acteur_id = DelegationActeurRepository.identifiant(acteur)
        return DelegationActeurRepository.actives(date_reference).filter(acteur_cible_id=acteur_id)

    @staticmethod
    def lister_actives_donnees(acteur, date_reference=None):
        acteur_id = DelegationActeurRepository.identifiant(acteur)
        return DelegationActeurRepository.actives(date_reference).filter(acteur_source_id=acteur_id)

    @staticmethod
    def lister_par_affectation(affectation, date_reference=None):
        affectation_id = DelegationActeurRepository.identifiant(affectation)
        return DelegationActeurRepository.actives(date_reference).filter(affectation_acteur_id=affectation_id)

    @staticmethod
    def delegation_active_existe(acteur_source, acteur_cible, affectation=None, date_reference=None):
        queryset = DelegationActeurRepository.actives(date_reference).filter(
            acteur_source_id=DelegationActeurRepository.identifiant(acteur_source),
            acteur_cible_id=DelegationActeurRepository.identifiant(acteur_cible),
        )

        if affectation is not None:
            queryset = queryset.filter(affectation_acteur_id=DelegationActeurRepository.identifiant(affectation))

        return queryset.exists()


class ControleAccesRepository(BaseRepository):
    """Requêtes transversales préparant le contrôle d'accès."""

    @staticmethod
    def get_permission_codes_roles(affectation, date_reference=None):
        role_ids = AffectationRoleRepository.lister_actifs_par_affectation(
            affectation,
            date_reference,
        ).values_list("role_id", flat=True)

        return RolePermissionRepository.actives().filter(role_id__in=role_ids).values_list(
            "permission__code",
            flat=True,
        ).distinct()

    @staticmethod
    def get_permission_codes_directes(affectation, date_reference=None):
        return AffectationPermissionRepository.lister_permissions_codes_par_affectation(
            affectation,
            date_reference,
        )

    @staticmethod
    def get_permission_codes_deleguees(acteur, affectation, date_reference=None):
        acteur_id = ControleAccesRepository.identifiant(acteur)
        affectation_id = ControleAccesRepository.identifiant(affectation)
        delegations = DelegationActeurRepository.actives(date_reference).filter(
            acteur_cible_id=acteur_id,
            affectation_acteur_id=affectation_id,
        )

        codes_directs = delegations.filter(
            type_delegation=DelegationActeur.TypeDelegation.PERMISSION,
            permission__deleted_at__isnull=True,
            permission__statut=Permission.Statut.ACTIVE,
        ).values_list("permission__code", flat=True)

        role_ids = delegations.filter(
            type_delegation=DelegationActeur.TypeDelegation.ROLE,
            role__deleted_at__isnull=True,
            role__statut=Role.Statut.ACTIF,
        ).values_list("role_id", flat=True)

        codes_roles = RolePermissionRepository.actives().filter(role_id__in=role_ids).values_list(
            "permission__code",
            flat=True,
        )

        return set(codes_directs).union(set(codes_roles))

    @staticmethod
    def get_permission_codes_acteur(acteur, affectation, date_reference=None):
        codes = set(ControleAccesRepository.get_permission_codes_roles(affectation, date_reference))
        codes.update(ControleAccesRepository.get_permission_codes_directes(affectation, date_reference))
        codes.update(ControleAccesRepository.get_permission_codes_deleguees(acteur, affectation, date_reference))
        return codes

    @staticmethod
    def acteur_a_permission(acteur, affectation, code_permission, date_reference=None):
        code_permission = ControleAccesRepository.normaliser_texte(code_permission)
        if not code_permission:
            return False
        return code_permission in ControleAccesRepository.get_permission_codes_acteur(
            acteur,
            affectation,
            date_reference,
        )
