from django.contrib import admin

from .models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)


class SoftDeleteAdminMixin:
    """Empêche la suppression physique depuis l'administration Django."""

    def delete_model(self, request, obj):
        if hasattr(obj, "supprimer_logiquement"):
            obj.supprimer_logiquement()
        else:
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            if hasattr(obj, "supprimer_logiquement"):
                obj.supprimer_logiquement()
            else:
                obj.delete()


@admin.register(RegionImmersion)
class RegionImmersionAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "nom", "statut", "deleted_at", "created_at")
    list_filter = ("statut", "deleted_at")
    search_fields = ("code", "nom")
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    ordering = ("nom",)

    fieldsets = (
        ("Identification", {
            "fields": ("code", "nom", "description"),
        }),
        ("État", {
            "fields": ("statut",),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )


@admin.register(CentreImmersion)
class CentreImmersionAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "nom",
        "region",
        "province",
        "ville",
        "genre",
        "statut",
        "deleted_at",
    )
    list_filter = ("region", "genre", "statut", "deleted_at")
    search_fields = ("code", "nom", "province", "ville")
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("region",)
    ordering = ("region__nom", "nom")

    fieldsets = (
        ("Identification", {
            "fields": ("region", "code", "nom"),
        }),
        ("Localisation", {
            "fields": ("province", "ville", "adresse"),
        }),
        ("Publics accueillis", {
            "fields": ("genre", "publics_acceptes", "niveaux_acceptes"),
        }),
        ("État", {
            "fields": ("statut",),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )


@admin.register(AffectationRegionale)
class AffectationRegionaleAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "immerge",
        "session",
        "region",
        "statut",
        "affecte_par",
        "date_affectation",
        "deleted_at",
    )
    list_filter = ("session", "region", "statut", "deleted_at")
    search_fields = (
        "immerge__code_fasoim",
        "region__code",
        "region__nom",
        "motif",
    )
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("immerge", "session", "region", "affecte_par")
    ordering = ("-date_affectation", "-id")

    fieldsets = (
        ("Affectation", {
            "fields": ("immerge", "session", "region", "statut"),
        }),
        ("Décision", {
            "fields": ("affecte_par", "date_affectation", "motif"),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )


@admin.register(AffectationCentre)
class AffectationCentreAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "immerge",
        "session",
        "centre",
        "statut",
        "affecte_par",
        "date_affectation",
        "deleted_at",
    )
    list_filter = ("session", "centre__region", "centre", "statut", "deleted_at")
    search_fields = (
        "immerge__code_fasoim",
        "centre__code",
        "centre__nom",
        "motif",
    )
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    autocomplete_fields = (
        "immerge",
        "session",
        "affectation_regionale",
        "centre",
        "affecte_par",
    )
    ordering = ("-date_affectation", "-id")

    fieldsets = (
        ("Affectation", {
            "fields": ("immerge", "session", "affectation_regionale", "centre", "statut"),
        }),
        ("Décision", {
            "fields": ("affecte_par", "date_affectation", "motif"),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )
