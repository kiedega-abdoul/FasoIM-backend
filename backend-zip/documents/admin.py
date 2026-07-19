from django.contrib import admin

from .models import DocumentGenere, PublicationOfficielle, ResultatFinal


class LectureSeuleApresPublicationMixin:
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ResultatFinal)
class ResultatFinalAdmin(LectureSeuleApresPublicationMixin, admin.ModelAdmin):
    list_display = (
        "immerge", "session", "centre", "decision", "statut",
        "taux_presence", "moyenne_sur_20", "date_calcul",
    )
    list_filter = ("session", "region", "centre", "decision", "statut", "evaluation_active")
    search_fields = ("immerge__code_fasoim", "centre__nom", "region__nom")
    readonly_fields = (
        "session", "region", "centre", "affectation_centre", "immerge",
        "total_seances", "total_eligible_presence", "presences_favorables",
        "presents", "retards", "absences", "excuses", "dispenses_presence",
        "taux_presence", "seuil_presence", "evaluation_active",
        "evaluations_applicables", "evaluations_cloturees", "notes_comptees",
        "absences_evaluation", "dispenses_evaluation", "somme_coefficients",
        "moyenne_sur_20", "seuil_moyenne_sur_20", "visite_medicale_active",
        "statut_medical_administratif", "participation_medicale_autorisee",
        "incident_bloquant", "decision", "motifs", "details_calcul", "statut",
        "version", "calcule_par", "valide_centre_par", "valide_region_par",
        "date_calcul", "date_validation_centre", "date_validation_region",
        "date_publication", "created_at", "updated_at", "deleted_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PublicationOfficielle)
class PublicationOfficielleAdmin(LectureSeuleApresPublicationMixin, admin.ModelAdmin):
    list_display = ("reference", "type_publication", "session", "centre", "statut", "version", "date_publication")
    list_filter = ("type_publication", "perimetre", "statut", "session", "region")
    search_fields = ("reference", "session__code", "centre__nom", "region__nom")
    readonly_fields = [field.name for field in PublicationOfficielle._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DocumentGenere)
class DocumentGenereAdmin(LectureSeuleApresPublicationMixin, admin.ModelAdmin):
    list_display = ("numero_document", "type_document", "session", "centre", "statut", "format_fichier", "date_generation")
    list_filter = ("type_document", "format_fichier", "statut", "visibilite", "session", "region")
    search_fields = ("numero_document", "titre", "immerge__code_fasoim", "centre__nom")
    readonly_fields = [field.name for field in DocumentGenere._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
