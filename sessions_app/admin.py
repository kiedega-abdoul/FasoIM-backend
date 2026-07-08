from django.contrib import admin

from .models import ParametreSession, SessionImmersion


class ParametreSessionInline(admin.StackedInline):
    model = ParametreSession
    extra = 0
    max_num = 1
    can_delete = False

    fieldsets = (
        (
            "Mode d'entrée",
            {
                "fields": (
                    "mode_entree",
                )
            },
        ),
        (
            "Modules activés",
            {
                "fields": (
                    "hebergement_active",
                    "repas_active",
                    "visite_medicale_active",
                    "mode_visite_medicale",
                    "activites_active",
                    "evaluation_active",
                    "attestation_active",
                    "consultation_publique_active",
                )
            },
        ),
        (
            "Attestation et consignes",
            {
                "fields": (
                    "taux_presence_minimum_attestation",
                    "directives_generales",
                    "consignes_generales",
                    "documents_exiges",
                )
            },
        ),
    )


@admin.register(SessionImmersion)
class SessionImmersionAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "nom",
        "annee",
        "numero_promotion",
        "type_session",
        "public_cible",
        "statut",
        "date_debut",
        "date_fin",
        "est_active_admin",
    ]
    list_filter = [
        "annee",
        "numero_promotion",
        "type_session",
        "public_cible",
        "statut",
    ]
    search_fields = [
        "code",
        "nom",
    ]
    readonly_fields = [
        "code",
        "est_active_admin",
        "est_modifiable_admin",
        "created_at",
        "updated_at",
        "deleted_at",
    ]
    ordering = ["-created_at"]
    date_hierarchy = "date_debut"
    inlines = [ParametreSessionInline]

    fieldsets = (
        (
            "Identification",
            {
                "fields": (
                    "nom",
                    "code",
                    "annee",
                    "numero_promotion",
                )
            },
        ),
        (
            "Type de session",
            {
                "fields": (
                    "type_session",
                    "public_cible",
                    "statut",
                )
            },
        ),
        (
            "Calendrier",
            {
                "fields": (
                    "date_debut",
                    "date_fin",
                    "date_ouverture_inscription",
                    "date_fermeture_inscription",
                )
            },
        ),
        (
            "Description",
            {
                "fields": (
                    "description",
                )
            },
        ),
        (
            "Contrôle système",
            {
                "classes": ("collapse",),
                "fields": (
                    "est_active_admin",
                    "est_modifiable_admin",
                    "created_at",
                    "updated_at",
                    "deleted_at",
                ),
            },
        ),
    )

    @admin.display(boolean=True, description="Active")
    def est_active_admin(self, obj):
        return obj.est_active

    @admin.display(boolean=True, description="Modifiable")
    def est_modifiable_admin(self, obj):
        return obj.est_modifiable


@admin.register(ParametreSession)
class ParametreSessionAdmin(admin.ModelAdmin):
    list_display = [
        "session",
        "mode_entree",
        "hebergement_active",
        "repas_active",
        "visite_medicale_active",
        "evaluation_active",
        "attestation_active",
        "taux_presence_minimum_attestation",
    ]
    list_filter = [
        "mode_entree",
        "hebergement_active",
        "repas_active",
        "visite_medicale_active",
        "activites_active",
        "evaluation_active",
        "attestation_active",
        "consultation_publique_active",
    ]
    search_fields = [
        "session__code",
        "session__nom",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "deleted_at",
    ]
    ordering = ["-created_at"]
