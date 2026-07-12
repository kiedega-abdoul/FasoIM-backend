from django.contrib import admin

from .models import (
    DemandeRavitaillementCentre,
    LigneBesoinDenree,
    RepasJournalier,
    SuiviRepas,
)


class SuppressionPhysiqueInterditeAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


class LigneBesoinDenreeInline(admin.TabularInline):
    model = LigneBesoinDenree
    extra = 0
    show_change_link = True
    fields = (
        "code_denree", "designation", "conditionnement", "unite_base",
        "quantite_demandee", "quantite_validee", "quantite_recue", "statut",
    )


@admin.register(DemandeRavitaillementCentre)
class DemandeRavitaillementAdmin(SuppressionPhysiqueInterditeAdmin):
    list_display = (
        "id", "session", "centre", "effectif_reference", "statut",
        "date_soumission", "date_validation",
    )
    list_filter = ("statut", "session", "centre__region")
    search_fields = ("session__code", "session__nom", "centre__code", "centre__nom")
    raw_id_fields = ("session", "centre", "soumis_par", "valide_par")
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    inlines = [LigneBesoinDenreeInline]


@admin.register(LigneBesoinDenree)
class LigneBesoinDenreeAdmin(SuppressionPhysiqueInterditeAdmin):
    list_display = (
        "id", "code_denree", "designation", "demande_ravitaillement",
        "quantite_demandee", "quantite_validee", "quantite_recue", "statut",
    )
    list_filter = ("statut", "conditionnement", "unite_base")
    search_fields = ("code_denree", "designation", "demande_ravitaillement__centre__nom")
    raw_id_fields = ("demande_ravitaillement",)
    readonly_fields = ("created_at", "updated_at", "deleted_at")


class SuiviRepasInline(admin.TabularInline):
    model = SuiviRepas
    extra = 0
    show_change_link = True
    fields = (
        "type_suivi", "groupe", "effectif_attendu", "nombre_ayant_mange",
        "affectation_centre", "statut_service",
    )


@admin.register(RepasJournalier)
class RepasJournalierAdmin(SuppressionPhysiqueInterditeAdmin):
    list_display = (
        "id", "date_repas", "type_repas", "centre", "menu_prevu",
        "nombre_standard_prevu", "statut_controle_sante", "statut",
    )
    list_filter = (
        "type_repas", "statut", "statut_controle_sante", "date_repas",
        "demande_ravitaillement__session", "demande_ravitaillement__centre",
    )
    search_fields = (
        "menu_prevu", "menu_prepare", "demande_ravitaillement__centre__nom",
        "demande_ravitaillement__session__code",
    )
    raw_id_fields = ("demande_ravitaillement", "cree_par", "valide_par")
    readonly_fields = (
        "nombre_standard_prevu", "synthese_restrictions_alimentaires",
        "statut_controle_sante", "date_verification_sante",
        "empreinte_besoins_sante", "date_validation",
        "date_ouverture_distribution", "date_cloture",
        "created_at", "updated_at", "deleted_at",
    )
    date_hierarchy = "date_repas"
    inlines = [SuiviRepasInline]

    @admin.display(description="Centre")
    def centre(self, obj):
        return obj.demande_ravitaillement.centre


@admin.register(SuiviRepas)
class SuiviRepasAdmin(SuppressionPhysiqueInterditeAdmin):
    list_display = (
        "id", "repas_journalier", "type_suivi", "groupe",
        "affectation_centre", "nombre_ayant_mange", "statut_service",
    )
    list_filter = ("type_suivi", "statut_service", "repas_journalier__date_repas")
    search_fields = (
        "affectation_centre__immerge__code_fasoim", "groupe__code",
        "consigne_alimentaire",
    )
    raw_id_fields = (
        "repas_journalier", "groupe", "affectation_centre", "saisi_par",
    )
    readonly_fields = ("created_at", "updated_at", "deleted_at")
