from django.contrib import admin

from .models import (
    CorrespondanceColonneImport,
    ErreurImport,
    ImportOfficiel,
    LigneImport,
)


class CorrespondanceColonneImportInline(admin.TabularInline):
    model = CorrespondanceColonneImport
    extra = 0
    fields = (
        "champ_cible",
        "libelle_champ_cible",
        "colonne_source",
        "obligatoire",
        "confirmee",
        "ordre",
    )
    show_change_link = True


@admin.register(ImportOfficiel)
class ImportOfficielAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "type_source",
        "session",
        "nom_fichier_original",
        "statut",
        "total_lignes",
        "lignes_valides",
        "lignes_erreur",
        "lignes_ignorees",
        "lignes_importees",
        "importe_par",
        "date_import",
    )
    list_filter = (
        "type_source",
        "type_fichier",
        "statut",
        "session",
        "deleted_at",
    )
    search_fields = (
        "nom_fichier_original",
        "hash_fichier",
        "message_erreur",
        "commentaire",
        "session__code",
        "session__nom",
        "importe_par__username",
        "importe_par__email",
    )
    readonly_fields = (
        "taille_fichier",
        "hash_fichier",
        "colonnes_detectees",
        "apercu_lignes",
        "total_lignes",
        "lignes_valides",
        "lignes_erreur",
        "lignes_ignorees",
        "lignes_importees",
        "date_import",
        "date_lecture_colonnes",
        "date_correspondance",
        "date_validation",
        "date_confirmation",
        "date_fin_traitement",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    raw_id_fields = (
        "session",
        "importe_par",
        "correspondance_confirmee_par",
        "confirme_par",
    )
    date_hierarchy = "date_import"
    inlines = [CorrespondanceColonneImportInline]
    fieldsets = (
        (
            "Fichier importé",
            {
                "fields": (
                    "session",
                    "type_source",
                    "type_fichier",
                    "fichier",
                    "nom_fichier_original",
                    "taille_fichier",
                    "hash_fichier",
                    "commentaire",
                )
            },
        ),
        (
            "Traitement",
            {
                "fields": (
                    "statut",
                    "colonnes_detectees",
                    "apercu_lignes",
                    "message_erreur",
                )
            },
        ),
        (
            "Statistiques",
            {
                "fields": (
                    "total_lignes",
                    "lignes_valides",
                    "lignes_erreur",
                    "lignes_ignorees",
                    "lignes_importees",
                )
            },
        ),
        (
            "Acteurs",
            {
                "fields": (
                    "importe_par",
                    "correspondance_confirmee_par",
                    "confirme_par",
                )
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "date_import",
                    "date_lecture_colonnes",
                    "date_correspondance",
                    "date_validation",
                    "date_confirmation",
                    "date_fin_traitement",
                )
            },
        ),
        (
            "Suivi technique",
            {
                "fields": ("created_at", "updated_at", "deleted_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(CorrespondanceColonneImport)
class CorrespondanceColonneImportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "import_officiel",
        "champ_cible",
        "colonne_source",
        "obligatoire",
        "confirmee",
        "ordre",
    )
    list_filter = ("obligatoire", "confirmee", "import_officiel__type_source", "deleted_at")
    search_fields = (
        "champ_cible",
        "libelle_champ_cible",
        "colonne_source",
        "import_officiel__nom_fichier_original",
    )
    raw_id_fields = ("import_officiel",)
    readonly_fields = ("created_at", "updated_at", "deleted_at")


@admin.register(LigneImport)
class LigneImportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "import_officiel",
        "numero_ligne",
        "statut",
        "message_court",
        "created_at",
    )
    list_filter = ("statut", "import_officiel__type_source", "import_officiel__statut", "deleted_at")
    search_fields = (
        "hash_ligne",
        "message_statut",
        "import_officiel__nom_fichier_original",
    )
    raw_id_fields = ("import_officiel",)
    readonly_fields = (
        "donnees_brutes",
        "donnees_normalisees",
        "hash_ligne",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    @admin.display(description="Message")
    def message_court(self, obj):
        if not obj.message_statut:
            return ""
        return obj.message_statut[:80]


@admin.register(ErreurImport)
class ErreurImportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "import_officiel",
        "numero_ligne",
        "champ_cible",
        "type_erreur",
        "gravite",
        "message_court",
    )
    list_filter = ("gravite", "type_erreur", "import_officiel__type_source", "deleted_at")
    search_fields = (
        "champ_cible",
        "colonne_source",
        "message",
        "valeur_recue",
        "code_erreur",
        "import_officiel__nom_fichier_original",
    )
    raw_id_fields = ("import_officiel", "ligne_import")
    readonly_fields = ("created_at", "updated_at", "deleted_at")

    @admin.display(description="Ligne")
    def numero_ligne(self, obj):
        return obj.ligne_import.numero_ligne if obj.ligne_import_id else ""

    @admin.display(description="Message")
    def message_court(self, obj):
        return obj.message[:100]
