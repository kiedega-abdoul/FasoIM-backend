from django.contrib import admin

from .models import AlerteIncident


@admin.register(AlerteIncident)
class AlerteIncidentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "type",
        "origine",
        "categorie",
        "niveau_gravite",
        "statut",
        "session",
        "centre",
        "cree_par",
        "traite_par",
        "date_signalement",
    )
    list_filter = (
        "type",
        "origine",
        "categorie",
        "niveau_gravite",
        "statut",
        "est_bloquante",
        "module_source",
    )
    search_fields = (
        "titre",
        "description",
        "code_detection",
        "cle_deduplication",
        "cree_par__username",
        "cree_par__email",
    )
    readonly_fields = (
        "nombre_occurrences",
        "date_premiere_detection",
        "date_derniere_detection",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "session",
        "centre",
        "affectation_centre",
        "acteur_concerne",
        "cree_par",
        "traite_par",
    )
