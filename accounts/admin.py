from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

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


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0
    autocomplete_fields = ["permission"]
    fields = [
        "permission",
        "est_delegable",
        "perimetre_delegation_max",
        "statut",
        "deleted_at",
    ]


class AffectationRoleInline(admin.TabularInline):
    model = AffectationRole
    extra = 0
    autocomplete_fields = ["role", "attribue_par"]
    fields = [
        "role",
        "date_attribution",
        "date_expiration",
        "statut",
        "attribue_par",
        "deleted_at",
    ]


class AffectationPermissionInline(admin.TabularInline):
    model = AffectationPermission
    extra = 0
    autocomplete_fields = ["permission", "attribue_par"]
    fields = [
        "permission",
        "date_attribution",
        "date_expiration",
        "est_delegable",
        "statut",
        "attribue_par",
        "deleted_at",
    ]


@admin.register(Acteur)
class ActeurAdmin(UserAdmin):
    list_display = [
        "username",
        "email",
        "nom_complet",
        "telephone",
        "statut",
        "is_staff",
        "is_active",
    ]
    list_filter = ["statut", "is_staff", "is_superuser", "is_active", "deleted_at"]
    search_fields = ["username", "email", "first_name", "last_name", "telephone"]
    ordering = ["last_name", "first_name", "username"]
    autocomplete_fields = ["created_by"]

    fieldsets = UserAdmin.fieldsets + (
        (
            "Informations FasoIM",
            {
                "fields": (
                    "telephone",
                    "titre",
                    "organisation",
                    "signature_image",
                    "cachet_image",
                    "statut",
                    "created_by",
                )
            },
        ),
        (
            "Suivi interne",
            {
                "classes": ("collapse",),
                "fields": ("deleted_at",),
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "telephone",
                    "password1",
                    "password2",
                    "statut",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["code", "libelle", "niveau", "perimetre_autorise", "statut", "est_systeme"]
    list_filter = ["perimetre_autorise", "statut", "est_systeme", "est_modifiable", "deleted_at"]
    search_fields = ["code", "libelle", "description"]
    ordering = ["niveau", "code"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [RolePermissionInline]

    fieldsets = [
        ("Identification", {"fields": ("code", "libelle", "description")}),
        ("Contrôle", {"fields": ("niveau", "perimetre_autorise", "est_systeme", "est_modifiable", "statut")}),
        ("Suivi interne", {"classes": ("collapse",), "fields": ("created_at", "updated_at", "deleted_at")}),
    ]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ["code", "libelle", "module", "statut", "est_systeme"]
    list_filter = ["module", "statut", "est_systeme", "deleted_at"]
    search_fields = ["code", "libelle", "module", "description"]
    ordering = ["module", "code"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = [
        ("Identification", {"fields": ("code", "libelle", "module", "description")}),
        ("Contrôle", {"fields": ("est_systeme", "statut")}),
        ("Suivi interne", {"classes": ("collapse",), "fields": ("created_at", "updated_at", "deleted_at")}),
    ]


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ["role", "permission", "est_delegable", "perimetre_delegation_max", "statut"]
    list_filter = ["statut", "est_delegable", "perimetre_delegation_max", "deleted_at"]
    search_fields = ["role__code", "role__libelle", "permission__code", "permission__libelle"]
    autocomplete_fields = ["role", "permission"]
    list_select_related = ["role", "permission"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(AffectationActeur)
class AffectationActeurAdmin(admin.ModelAdmin):
    list_display = [
        "acteur",
        "niveau_affectation",
        "session_id",
        "region_code",
        "centre_id",
        "statut",
        "date_debut",
        "date_fin",
    ]
    list_filter = ["niveau_affectation", "statut", "region_code", "deleted_at"]
    search_fields = ["acteur__username", "acteur__email", "acteur__first_name", "acteur__last_name", "region_code"]
    autocomplete_fields = ["acteur", "affecte_par"]
    list_select_related = ["acteur", "affecte_par"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [AffectationRoleInline, AffectationPermissionInline]

    fieldsets = [
        ("Acteur", {"fields": ("acteur", "affecte_par")}),
        ("Périmètre", {"fields": ("niveau_affectation", "session_id", "region_code", "centre_id")}),
        ("Validité", {"fields": ("date_debut", "date_fin", "statut")}),
        ("Suivi interne", {"classes": ("collapse",), "fields": ("created_at", "updated_at", "deleted_at")}),
    ]


@admin.register(AffectationRole)
class AffectationRoleAdmin(admin.ModelAdmin):
    list_display = ["affectation_acteur", "role", "statut", "date_attribution", "date_expiration"]
    list_filter = ["statut", "role__perimetre_autorise", "deleted_at"]
    search_fields = ["affectation_acteur__acteur__username", "affectation_acteur__acteur__email", "role__code", "role__libelle"]
    autocomplete_fields = ["affectation_acteur", "role", "attribue_par"]
    list_select_related = ["affectation_acteur", "affectation_acteur__acteur", "role", "attribue_par"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(AffectationPermission)
class AffectationPermissionAdmin(admin.ModelAdmin):
    list_display = ["affectation_acteur", "permission", "statut", "est_delegable", "date_attribution", "date_expiration"]
    list_filter = ["statut", "est_delegable", "permission__module", "deleted_at"]
    search_fields = ["affectation_acteur__acteur__username", "affectation_acteur__acteur__email", "permission__code", "permission__libelle"]
    autocomplete_fields = ["affectation_acteur", "permission", "attribue_par"]
    list_select_related = ["affectation_acteur", "affectation_acteur__acteur", "permission", "attribue_par"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(DemandePermission)
class DemandePermissionAdmin(admin.ModelAdmin):
    list_display = ["acteur", "permission", "statut", "date_demande", "date_decision", "decideur"]
    list_filter = ["statut", "permission__module", "deleted_at"]
    search_fields = ["acteur__username", "acteur__email", "permission__code", "permission__libelle", "justification"]
    autocomplete_fields = ["acteur", "affectation_acteur", "permission", "decideur"]
    list_select_related = ["acteur", "affectation_acteur", "permission", "decideur"]
    readonly_fields = ["date_demande", "created_at", "updated_at"]
