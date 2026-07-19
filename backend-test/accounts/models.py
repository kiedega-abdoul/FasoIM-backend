from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Acteur(AbstractUser):
    """Utilisateur interne FasoIM."""

    class Statut(models.TextChoices):
        ACTIF = "actif", "Actif"
        SUSPENDU = "suspendu", "Suspendu"
        DESACTIVE = "desactive", "Désactivé"

    email = models.EmailField(unique=True)
    telephone = models.CharField(max_length=30, blank=True, null=True, unique=True)
    titre = models.CharField(max_length=150, blank=True)
    organisation = models.CharField(max_length=200, blank=True)
    signature_image = models.ImageField(upload_to="acteurs/signatures/", blank=True, null=True)
    cachet_image = models.ImageField(upload_to="acteurs/cachets/", blank=True, null=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIF,
        db_index=True,
    )
    created_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="acteurs_crees",
        blank=True,
        null=True,
    )
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    REQUIRED_FIELDS = ["email", "first_name", "last_name"]

    class Meta:
        db_table = "acteurs"
        verbose_name = "acteur"
        verbose_name_plural = "acteurs"
        ordering = ["last_name", "first_name", "username"]

    def __str__(self):
        nom = self.nom_complet
        return nom or self.username or self.email

    @property
    def nom_complet(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def est_actif_metier(self):
        return self.is_active and self.statut == self.Statut.ACTIF and self.deleted_at is None


class Role(models.Model):
    """Rôle métier regroupant des permissions système."""

    class Perimetre(models.TextChoices):
        PLATEFORME = "plateforme", "Plateforme"
        NATIONAL = "national", "National"
        REGION = "region", "Région"
        CENTRE = "centre", "Centre"

    class Statut(models.TextChoices):
        ACTIF = "actif", "Actif"
        INACTIF = "inactif", "Inactif"

    code = models.CharField(max_length=80, unique=True, db_index=True)
    libelle = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    niveau = models.PositiveSmallIntegerField(default=100, db_index=True)
    perimetre_autorise = models.CharField(
        max_length=30,
        choices=Perimetre.choices,
        default=Perimetre.NATIONAL,
        db_index=True,
    )
    est_systeme = models.BooleanField(default=True)
    est_modifiable = models.BooleanField(default=False)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIF,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "roles"
        verbose_name = "rôle"
        verbose_name_plural = "rôles"
        ordering = ["niveau", "code"]

    def __str__(self):
        return self.libelle

    @property
    def est_actif(self):
        return self.statut == self.Statut.ACTIF and self.deleted_at is None


class Permission(models.Model):
    """Permission système correspondant à une action réellement codée."""

    class Statut(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    code = models.CharField(max_length=120, unique=True, db_index=True)
    libelle = models.CharField(max_length=180)
    module = models.CharField(max_length=80, db_index=True)
    description = models.TextField(blank=True)
    est_systeme = models.BooleanField(default=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIVE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "permissions"
        verbose_name = "permission"
        verbose_name_plural = "permissions"
        ordering = ["module", "code"]

    def __str__(self):
        return self.code

    @property
    def est_active(self):
        return self.statut == self.Statut.ACTIVE and self.deleted_at is None


class RolePermission(models.Model):
    """Permission accordée à un rôle."""

    class Statut(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDUE = "suspendue", "Suspendue"
        RETIREE = "retiree", "Retirée"

    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="permissions_role",
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.PROTECT,
        related_name="roles_permission",
    )
    est_delegable = models.BooleanField(default=False)
    perimetre_delegation_max = models.CharField(
        max_length=30,
        choices=Role.Perimetre.choices,
        blank=True,
    )
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIVE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "role_permissions"
        verbose_name = "permission de rôle"
        verbose_name_plural = "permissions de rôles"
        ordering = ["role__niveau", "role__code", "permission__module", "permission__code"]

    def __str__(self):
        return f"{self.role.code} → {self.permission.code}"

    @property
    def est_active(self):
        return self.statut == self.Statut.ACTIVE and self.deleted_at is None


class AffectationActeur(models.Model):
    """Périmètre dans lequel un acteur peut agir."""

    class NiveauAffectation(models.TextChoices):
        PLATEFORME = "plateforme", "Plateforme"
        NATIONAL = "national", "National"
        REGION = "region", "Région"
        CENTRE = "centre", "Centre"

    SESSION_STATUTS_ACTIFS = ("ouverte", "en_preparation", "en_cours")

    class Statut(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDUE = "suspendue", "Suspendue"
        TERMINEE = "terminee", "Terminée"
        ANNULEE = "annulee", "Annulée"

    acteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="affectations",
    )
    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="affectations_acteurs",
        blank=True,
        null=True,
    )
    niveau_affectation = models.CharField(
        max_length=30,
        choices=NiveauAffectation.choices,
        default=NiveauAffectation.NATIONAL,
        db_index=True,
    )
    region_code = models.CharField(max_length=30, blank=True, db_index=True)
    centre_id = models.PositiveBigIntegerField(blank=True, null=True, db_index=True)
    date_debut = models.DateField(default=timezone.localdate)
    date_fin = models.DateField(blank=True, null=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIVE,
        db_index=True,
    )
    affecte_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="affectations_creees",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "affectations_acteurs"
        verbose_name = "affectation d'acteur"
        verbose_name_plural = "affectations d'acteurs"
        ordering = ["-date_debut", "niveau_affectation", "region_code", "centre_id"]

    def __str__(self):
        return f"{self.acteur} - {self.niveau_affectation}"

    def clean(self):
        if self.date_fin and self.date_fin < self.date_debut:
            raise ValidationError({"date_fin": "La date de fin ne peut pas précéder la date de début."})

        if self.session_id and self.session and self.session.statut not in self.SESSION_STATUTS_ACTIFS:
            raise ValidationError({"session": "Une affectation liée à une session exige une session opérationnelle."})

        if self.session_id is None and self.niveau_affectation not in {
            self.NiveauAffectation.PLATEFORME,
            self.NiveauAffectation.NATIONAL,
        }:
            raise ValidationError({
                "session": (
                    "Une affectation permanente est autorisée uniquement "
                    "aux niveaux plateforme et national."
                )
            })

        if self.niveau_affectation == self.NiveauAffectation.REGION and not self.region_code:
            raise ValidationError({"region_code": "La région est obligatoire pour une affectation régionale."})

        if self.niveau_affectation == self.NiveauAffectation.CENTRE and not self.centre_id:
            raise ValidationError({"centre_id": "Le centre est obligatoire pour une affectation centre."})

    @property
    def est_active(self):
        aujourd_hui = timezone.localdate()
        session_operationnelle = (
            self.session_id is None
            or (self.session is not None and self.session.statut in self.SESSION_STATUTS_ACTIFS)
        )
        return (
            self.statut == self.Statut.ACTIVE
            and self.deleted_at is None
            and self.date_debut <= aujourd_hui
            and (self.date_fin is None or self.date_fin >= aujourd_hui)
            and session_operationnelle
        )


class AffectationRole(models.Model):
    """Rôle attribué à un acteur dans une affectation précise."""

    class Statut(models.TextChoices):
        ACTIF = "actif", "Actif"
        SUSPENDU = "suspendu", "Suspendu"
        RETIRE = "retire", "Retiré"
        EXPIRE = "expire", "Expiré"

    affectation_acteur = models.ForeignKey(
        AffectationActeur,
        on_delete=models.PROTECT,
        related_name="roles_affectes",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="affectations_roles",
    )
    date_attribution = models.DateField(default=timezone.localdate)
    date_expiration = models.DateField(blank=True, null=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIF,
        db_index=True,
    )
    attribue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="roles_attribues",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "affectation_roles"
        verbose_name = "rôle d'affectation"
        verbose_name_plural = "rôles d'affectations"
        ordering = ["-date_attribution", "role__niveau"]

    def __str__(self):
        return f"{self.affectation_acteur} → {self.role}"

    def clean(self):
        if self.date_expiration and self.date_expiration < self.date_attribution:
            raise ValidationError({"date_expiration": "La date d'expiration ne peut pas précéder l'attribution."})

    @property
    def est_actif(self):
        aujourd_hui = timezone.localdate()
        return (
            self.statut == self.Statut.ACTIF
            and self.deleted_at is None
            and self.date_attribution <= aujourd_hui
            and (self.date_expiration is None or self.date_expiration >= aujourd_hui)
        )


class AffectationPermission(models.Model):
    """Permission exceptionnelle attribuée directement à une affectation."""

    class Statut(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDUE = "suspendue", "Suspendue"
        RETIREE = "retiree", "Retirée"
        EXPIREE = "expiree", "Expirée"

    affectation_acteur = models.ForeignKey(
        AffectationActeur,
        on_delete=models.PROTECT,
        related_name="permissions_directes",
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.PROTECT,
        related_name="affectations_permissions",
    )
    date_attribution = models.DateField(default=timezone.localdate)
    date_expiration = models.DateField(blank=True, null=True)
    est_delegable = models.BooleanField(default=False)
    motif = models.TextField(blank=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIVE,
        db_index=True,
    )
    attribue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="permissions_attribuees",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "affectation_permissions"
        verbose_name = "permission directe"
        verbose_name_plural = "permissions directes"
        ordering = ["-date_attribution", "permission__code"]

    def __str__(self):
        return f"{self.affectation_acteur} → {self.permission.code}"

    def clean(self):
        if self.date_expiration and self.date_expiration < self.date_attribution:
            raise ValidationError({"date_expiration": "La date d'expiration ne peut pas précéder l'attribution."})

    @property
    def est_active(self):
        aujourd_hui = timezone.localdate()
        return (
            self.statut == self.Statut.ACTIVE
            and self.deleted_at is None
            and self.date_attribution <= aujourd_hui
            and (self.date_expiration is None or self.date_expiration >= aujourd_hui)
        )


class DemandePermission(models.Model):
    """Demande de permission supplémentaire par un acteur."""

    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente"
        APPROUVEE = "approuvee", "Approuvée"
        REFUSEE = "refusee", "Refusée"
        ANNULEE = "annulee", "Annulée"

    acteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="demandes_permissions",
    )
    affectation_acteur = models.ForeignKey(
        AffectationActeur,
        on_delete=models.PROTECT,
        related_name="demandes_permissions",
        blank=True,
        null=True,
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.PROTECT,
        related_name="demandes_permissions",
    )
    justification = models.TextField()
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.EN_ATTENTE,
        db_index=True,
    )
    date_demande = models.DateTimeField(auto_now_add=True)
    date_decision = models.DateTimeField(blank=True, null=True)
    decideur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="decisions_permissions",
        blank=True,
        null=True,
    )
    motif_decision = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "demandes_permissions"
        verbose_name = "demande de permission"
        verbose_name_plural = "demandes de permissions"
        ordering = ["-date_demande"]

    def __str__(self):
        return f"{self.acteur} demande {self.permission.code}"

    @property
    def est_en_attente(self):
        return self.statut == self.Statut.EN_ATTENTE and self.deleted_at is None


class DelegationActeur(models.Model):
    """Délégation temporaire d'un rôle ou d'une permission à un autre acteur."""

    class TypeDelegation(models.TextChoices):
        ROLE = "role", "Rôle"
        PERMISSION = "permission", "Permission"

    class Statut(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDUE = "suspendue", "Suspendue"
        TERMINEE = "terminee", "Terminée"
        ANNULEE = "annulee", "Annulée"

    acteur_source = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delegations_donnees",
    )
    acteur_cible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delegations_recues",
    )
    affectation_acteur = models.ForeignKey(
        AffectationActeur,
        on_delete=models.PROTECT,
        related_name="delegations",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="delegations",
        blank=True,
        null=True,
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.PROTECT,
        related_name="delegations",
        blank=True,
        null=True,
    )
    type_delegation = models.CharField(
        max_length=20,
        choices=TypeDelegation.choices,
        db_index=True,
    )
    date_debut = models.DateField(default=timezone.localdate)
    date_fin = models.DateField()
    motif = models.TextField(blank=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIVE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "delegations_acteurs"
        verbose_name = "délégation d'acteur"
        verbose_name_plural = "délégations d'acteurs"
        ordering = ["-date_debut", "-date_fin"]

    def __str__(self):
        return f"{self.acteur_source} → {self.acteur_cible} ({self.type_delegation})"

    def clean(self):
        if self.date_fin < self.date_debut:
            raise ValidationError({"date_fin": "La date de fin ne peut pas précéder la date de début."})

        if self.acteur_source_id and self.acteur_cible_id and self.acteur_source_id == self.acteur_cible_id:
            raise ValidationError({"acteur_cible": "Un acteur ne peut pas se déléguer à lui-même."})

        if self.type_delegation == self.TypeDelegation.ROLE and not self.role:
            raise ValidationError({"role": "Le rôle est obligatoire pour une délégation de rôle."})

        if self.type_delegation == self.TypeDelegation.PERMISSION and not self.permission:
            raise ValidationError({"permission": "La permission est obligatoire pour une délégation de permission."})

    @property
    def est_active(self):
        aujourd_hui = timezone.localdate()
        return (
            self.statut == self.Statut.ACTIVE
            and self.deleted_at is None
            and self.date_debut <= aujourd_hui <= self.date_fin
        )
