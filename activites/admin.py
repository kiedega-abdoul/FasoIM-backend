from django.contrib import admin

from .models import (
    Evaluation,
    ModuleActivite,
    Note,
    Presence,
    Seance,
)


class SuppressionPhysiqueInterditeAdmin(admin.ModelAdmin):
    """Les suppressions métier passent par les services."""

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ModuleActivite)
class ModuleActiviteAdmin(SuppressionPhysiqueInterditeAdmin):
    list_display = (
        "id",
        "ordre",
        "code",
        "titre",
        "categorie",
        "duree_affichee",
        "statut",
    )
    list_filter = (
        "categorie",
        "statut",
    )
    search_fields = (
        "code",
        "titre",
        "description",
    )
    ordering = (
        "ordre",
        "categorie",
        "titre",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
    )
    fieldsets = (
        (
            "Module réutilisable",
            {
                "fields": (
                    "code",
                    "titre",
                    "description",
                    "categorie",
                    "duree_prevue",
                    "ordre",
                    "statut",
                )
            },
        ),
        (
            "Traçabilité",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "deleted_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Durée prévue")
    def duree_affichee(self, obj):
        if obj.duree_prevue is None:
            return "Non définie"
        return f"{obj.duree_prevue} min"


@admin.register(Seance)
class SeanceAdmin(SuppressionPhysiqueInterditeAdmin):
    list_display = (
        "id",
        "titre",
        "module_activite",
        "session",
        "centre",
        "cible",
        "date_seance",
        "horaire",
        "formateur",
        "statut",
        "statut_feuille_presence",
    )
    list_filter = (
        "statut",
        "statut_feuille_presence",
        "date_seance",
        "module_activite__categorie",
        "session",
        "centre",
    )
    search_fields = (
        "titre",
        "module_activite__code",
        "module_activite__titre",
        "session__code",
        "session__nom",
        "centre__code",
        "centre__nom",
        "section__code",
        "section__nom",
        "groupe__code",
        "groupe__nom",
        "lieu",
        "formateur__username",
        "formateur__email",
    )
    ordering = (
        "-date_seance",
        "heure_debut",
    )
    date_hierarchy = "date_seance"
    raw_id_fields = (
        "module_activite",
        "session",
        "centre",
        "section",
        "groupe",
        "formateur",
        "presences_validees_par",
    )
    list_select_related = (
        "module_activite",
        "session",
        "centre",
        "section",
        "groupe",
        "formateur",
        "presences_validees_par",
    )
    readonly_fields = (
        "date_ouverture_presence",
        "date_validation_presence",
        "date_cloture_presence",
        "presences_validees_par",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    fieldsets = (
        (
            "Planification",
            {
                "fields": (
                    "module_activite",
                    "session",
                    "centre",
                    "section",
                    "groupe",
                    "formateur",
                )
            },
        ),
        (
            "Séance",
            {
                "fields": (
                    "titre",
                    "date_seance",
                    "heure_debut",
                    "heure_fin",
                    "lieu",
                    "statut",
                    "observations",
                )
            },
        ),
        (
            "Feuille de présence",
            {
                "fields": (
                    "statut_feuille_presence",
                    "date_ouverture_presence",
                    "date_validation_presence",
                    "date_cloture_presence",
                    "presences_validees_par",
                )
            },
        ),
        (
            "Traçabilité",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "deleted_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Cible")
    def cible(self, obj):
        if obj.groupe_id:
            return f"Groupe : {obj.groupe.nom}"
        if obj.section_id:
            return f"Section : {obj.section.nom}"
        return "Tout le centre"

    @admin.display(description="Horaire")
    def horaire(self, obj):
        return f"{obj.heure_debut} - {obj.heure_fin}"


@admin.register(Presence)
class PresenceAdmin(SuppressionPhysiqueInterditeAdmin):
    list_display = (
        "id",
        "code_fasoim",
        "seance",
        "statut_presence",
        "heure_arrivee",
        "date_saisie",
        "saisie_par",
    )
    list_filter = (
        "statut_presence",
        "date_saisie",
        "seance__date_seance",
        "seance__session",
        "seance__centre",
    )
    search_fields = (
        "affectation_centre__immerge__code_fasoim",
        "seance__titre",
        "seance__module_activite__code",
        "seance__module_activite__titre",
        "observations",
        "saisie_par__username",
        "saisie_par__email",
    )
    ordering = (
        "-seance__date_seance",
        "affectation_centre__immerge__code_fasoim",
    )
    date_hierarchy = "date_saisie"
    raw_id_fields = (
        "seance",
        "affectation_centre",
        "saisie_par",
    )
    list_select_related = (
        "seance",
        "seance__module_activite",
        "affectation_centre",
        "affectation_centre__immerge",
        "saisie_par",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
    )

    @admin.display(description="Code FasoIM")
    def code_fasoim(self, obj):
        return obj.affectation_centre.immerge.code_fasoim


@admin.register(Evaluation)
class EvaluationAdmin(SuppressionPhysiqueInterditeAdmin):
    list_display = (
        "id",
        "titre",
        "module_lie",
        "session",
        "centre",
        "type_evaluation",
        "bareme",
        "coefficient",
        "date_evaluation",
        "statut",
        "created_by",
    )
    list_filter = (
        "type_evaluation",
        "statut",
        "session",
        "centre",
        "date_evaluation",
    )
    search_fields = (
        "titre",
        "seance__titre",
        "seance__module_activite__code",
        "seance__module_activite__titre",
        "session__code",
        "session__nom",
        "centre__code",
        "centre__nom",
        "created_by__username",
        "created_by__email",
    )
    ordering = ("-date_evaluation",)
    date_hierarchy = "date_evaluation"
    raw_id_fields = (
        "session",
        "centre",
        "seance",
        "created_by",
    )
    list_select_related = (
        "session",
        "centre",
        "seance",
        "seance__module_activite",
        "created_by",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
    )

    @admin.display(description="Module lié")
    def module_lie(self, obj):
        if not obj.seance_id:
            return "Évaluation indépendante"
        return obj.seance.module_activite.titre


@admin.register(Note)
class NoteAdmin(SuppressionPhysiqueInterditeAdmin):
    list_display = (
        "id",
        "code_fasoim",
        "evaluation",
        "valeur",
        "statut_note",
        "date_saisie",
        "saisie_par",
    )
    list_filter = (
        "statut_note",
        "date_saisie",
        "evaluation__type_evaluation",
        "evaluation__session",
        "evaluation__centre",
    )
    search_fields = (
        "affectation_centre__immerge__code_fasoim",
        "evaluation__titre",
        "evaluation__seance__module_activite__code",
        "evaluation__seance__module_activite__titre",
        "appreciation",
        "observations",
        "saisie_par__username",
        "saisie_par__email",
    )
    ordering = (
        "-evaluation__date_evaluation",
        "affectation_centre__immerge__code_fasoim",
    )
    date_hierarchy = "date_saisie"
    raw_id_fields = (
        "evaluation",
        "affectation_centre",
        "saisie_par",
    )
    list_select_related = (
        "evaluation",
        "evaluation__seance",
        "evaluation__seance__module_activite",
        "affectation_centre",
        "affectation_centre__immerge",
        "saisie_par",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
    )

    @admin.display(description="Code FasoIM")
    def code_fasoim(self, obj):
        return obj.affectation_centre.immerge.code_fasoim
