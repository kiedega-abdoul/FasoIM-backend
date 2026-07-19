from django.contrib import admin

from .models import (
    AffectationGroupe,
    AttributionLit,
    Dortoir,
    Groupe,
    Lit,
    RegleOrganisationCentre,
    Section,
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


@admin.register(RegleOrganisationCentre)
class RegleOrganisationCentreAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "session",
        "centre",
        "seuil_division_sections",
        "seuil_division_groupes",
        "hebergement_session",
        "visite_medicale_session",
        "statut",
        "date_validation",
        "deleted_at",
    )
    list_filter = (
        "statut",
        "session",
        "centre__region",
        "centre",
        "repartition_sections_groupes_automatique",
        "attribution_lits_automatique",
        "deleted_at",
    )
    search_fields = (
        "session__code",
        "session__nom",
        "centre__code",
        "centre__nom",
        "lieu_accueil",
        "directives_locales",
        "consignes_internes",
    )
    readonly_fields = (
        "date_validation",
        "date_pret_publication",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    autocomplete_fields = ("session", "centre", "validee_par")
    list_select_related = ("session", "centre", "centre__region")
    ordering = ("-session__annee", "centre__nom")

    fieldsets = (
        ("Périmètre", {
            "fields": ("session", "centre"),
        }),
        ("Sections et groupes", {
            "fields": (
                "seuil_division_sections",
                "capacite_max_section",
                "seuil_division_groupes",
                "capacite_max_groupe",
                "repartition_sections_groupes_automatique",
            ),
        }),
        ("Hébergement", {
            "fields": (
                "attribution_lits_automatique",
                "consignes_hebergement",
            ),
        }),
        ("Accueil et horaires", {
            "fields": (
                "lieu_accueil",
                "heure_accueil",
                "horaires_generaux",
                "consignes_accueil",
            ),
        }),
        ("Règles locales", {
            "fields": (
                "consignes_kits_a_apporter",
                "consignes_repas",
                "regles_discipline",
                "consignes_internes",
                "directives_locales",
            ),
        }),
        ("Validation", {
            "fields": (
                "statut",
                "validee_par",
                "date_validation",
                "date_pret_publication",
            ),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )

    @admin.display(boolean=True, description="Hébergement")
    def hebergement_session(self, obj):
        return obj.hebergement_active

    @admin.display(boolean=True, description="Visite médicale")
    def visite_medicale_session(self, obj):
        return obj.visite_medicale_active


@admin.register(Section)
class SectionAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "nom",
        "session",
        "centre",
        "capacite_max",
        "statut",
        "deleted_at",
    )
    list_filter = (
        "session",
        "centre__region",
        "centre",
        "statut",
        "deleted_at",
    )
    search_fields = (
        "code",
        "nom",
        "session__code",
        "centre__code",
        "centre__nom",
    )
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("session", "centre")
    list_select_related = ("session", "centre", "centre__region")
    ordering = ("session", "centre__nom", "code")

    fieldsets = (
        ("Section", {
            "fields": (
                "session",
                "centre",
                "code",
                "nom",
                "capacite_max",
                "statut",
            ),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )


@admin.register(Groupe)
class GroupeAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "nom",
        "section",
        "centre",
        "session",
        "capacite_max",
        "statut",
        "deleted_at",
    )
    list_filter = (
        "section__session",
        "section__centre__region",
        "section__centre",
        "statut",
        "deleted_at",
    )
    search_fields = (
        "code",
        "nom",
        "section__code",
        "section__nom",
        "section__centre__code",
        "section__centre__nom",
    )
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("section",)
    list_select_related = (
        "section",
        "section__session",
        "section__centre",
    )
    ordering = ("section__code", "code")

    fieldsets = (
        ("Groupe", {
            "fields": (
                "section",
                "code",
                "nom",
                "capacite_max",
                "statut",
            ),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )

    @admin.display(description="Centre")
    def centre(self, obj):
        return obj.section.centre

    @admin.display(description="Session")
    def session(self, obj):
        return obj.section.session


@admin.register(AffectationGroupe)
class AffectationGroupeAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "immerge",
        "centre",
        "section",
        "groupe",
        "statut",
        "affecte_par",
        "date_affectation",
        "deleted_at",
    )
    list_filter = (
        "affectation_centre__session",
        "affectation_centre__centre__region",
        "affectation_centre__centre",
        "groupe__section",
        "statut",
        "deleted_at",
    )
    search_fields = (
        "affectation_centre__immerge__code_fasoim",
        "affectation_centre__centre__code",
        "affectation_centre__centre__nom",
        "groupe__code",
        "groupe__nom",
        "observations",
    )
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    autocomplete_fields = (
        "affectation_centre",
        "groupe",
        "affecte_par",
    )
    list_select_related = (
        "affectation_centre",
        "affectation_centre__immerge",
        "affectation_centre__centre",
        "groupe",
        "groupe__section",
        "affecte_par",
    )
    ordering = ("-date_affectation", "-id")

    fieldsets = (
        ("Affectation interne", {
            "fields": (
                "affectation_centre",
                "groupe",
                "statut",
            ),
        }),
        ("Décision", {
            "fields": (
                "affecte_par",
                "date_affectation",
                "observations",
            ),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )

    @admin.display(description="Immergé")
    def immerge(self, obj):
        return obj.affectation_centre.immerge

    @admin.display(description="Centre")
    def centre(self, obj):
        return obj.affectation_centre.centre

    @admin.display(description="Section")
    def section(self, obj):
        return obj.groupe.section


@admin.register(Dortoir)
class DortoirAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "nom",
        "centre",
        "capacite",
        "sexe_dortoir",
        "statut",
        "deleted_at",
    )
    list_filter = (
        "centre__region",
        "centre",
        "sexe_dortoir",
        "statut",
        "deleted_at",
    )
    search_fields = (
        "nom",
        "centre__code",
        "centre__nom",
    )
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("centre",)
    list_select_related = ("centre", "centre__region")
    ordering = ("centre__nom", "nom")

    fieldsets = (
        ("Dortoir", {
            "fields": (
                "centre",
                "nom",
                "capacite",
                "sexe_dortoir",
                "statut",
            ),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )


@admin.register(Lit)
class LitAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "numero_lit",
        "dortoir",
        "centre",
        "sexe_dortoir",
        "statut",
        "deleted_at",
    )
    list_filter = (
        "dortoir__centre__region",
        "dortoir__centre",
        "dortoir__sexe_dortoir",
        "statut",
        "deleted_at",
    )
    search_fields = (
        "numero_lit",
        "dortoir__nom",
        "dortoir__centre__code",
        "dortoir__centre__nom",
    )
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    autocomplete_fields = ("dortoir",)
    list_select_related = ("dortoir", "dortoir__centre")
    ordering = ("dortoir__nom", "numero_lit")

    fieldsets = (
        ("Lit", {
            "fields": ("dortoir", "numero_lit", "statut"),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )

    @admin.display(description="Centre")
    def centre(self, obj):
        return obj.dortoir.centre

    @admin.display(description="Sexe")
    def sexe_dortoir(self, obj):
        return obj.dortoir.get_sexe_dortoir_display()


@admin.register(AttributionLit)
class AttributionLitAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "immerge",
        "centre",
        "dortoir",
        "lit",
        "statut",
        "attribue_par",
        "date_attribution",
        "date_liberation",
        "deleted_at",
    )
    list_filter = (
        "affectation_centre__session",
        "affectation_centre__centre__region",
        "affectation_centre__centre",
        "lit__dortoir",
        "statut",
        "deleted_at",
    )
    search_fields = (
        "affectation_centre__immerge__code_fasoim",
        "affectation_centre__centre__code",
        "affectation_centre__centre__nom",
        "lit__numero_lit",
        "lit__dortoir__nom",
        "observations",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
    )
    autocomplete_fields = (
        "affectation_centre",
        "lit",
        "attribue_par",
    )
    list_select_related = (
        "affectation_centre",
        "affectation_centre__immerge",
        "affectation_centre__centre",
        "lit",
        "lit__dortoir",
        "attribue_par",
    )
    ordering = ("-date_attribution", "-id")

    fieldsets = (
        ("Attribution", {
            "fields": (
                "affectation_centre",
                "lit",
                "statut",
            ),
        }),
        ("Décision", {
            "fields": (
                "attribue_par",
                "date_attribution",
                "date_liberation",
                "observations",
            ),
        }),
        ("Traçabilité", {
            "fields": ("created_at", "updated_at", "deleted_at"),
        }),
    )

    @admin.display(description="Immergé")
    def immerge(self, obj):
        return obj.affectation_centre.immerge

    @admin.display(description="Centre")
    def centre(self, obj):
        return obj.affectation_centre.centre

    @admin.display(description="Dortoir")
    def dortoir(self, obj):
        return obj.lit.dortoir
