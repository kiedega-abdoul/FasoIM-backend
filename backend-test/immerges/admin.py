from django.contrib import admin

from .models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
)


@admin.register(ImmergeExamen)
class ImmergeExamenAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "numero_pv",
        "type_examen",
        "serie",
        "annee_obtention",
        "identite_affichable",
        "sexe",
        "region_examen",
        "statut_validation",
    ]
    list_filter = ["type_examen", "annee_obtention", "statut_validation", "region_examen", "deleted_at"]
    search_fields = ["numero_pv", "nom", "prenoms", "nom_et_prenoms", "numero_cnib", "telephone", "email"]
    readonly_fields = ["created_at", "updated_at", "deleted_at"]
    ordering = ["-id"]

    fieldsets = (
        ("Import", {"fields": ("import_officiel", "numero_ligne_import")}),
        ("Examen", {"fields": ("numero_pv", "type_examen", "serie", "annee_obtention", "statut")}),
        ("Identité", {"fields": ("nom", "prenoms", "nom_et_prenoms", "sexe", "date_naissance", "lieu_naissance", "nationalite", "numero_cnib")}),
        ("Contacts", {"fields": ("telephone", "email", "contact_urgence", "nom_contact_urgence")}),
        ("Origine", {"fields": ("centre_examen", "etablissement_origine", "region_examen", "province_examen")}),
        ("Validation", {"fields": ("statut_validation", "donnees_brutes", "donnees_normalisees")}),
        ("Suivi", {"fields": ("created_at", "updated_at", "deleted_at")}),
    )


@admin.register(ImmergeConcours)
class ImmergeConcoursAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "numero_recepisse",
        "identite_affichable",
        "sexe",
        "specialite",
        "region_composition",
        "statut_validation",
    ]
    list_filter = ["statut_validation", "region_composition", "province_composition", "deleted_at"]
    search_fields = ["numero_recepisse", "nom", "prenoms", "nom_et_prenoms", "numero_cnib", "telephone", "email", "specialite"]
    readonly_fields = ["created_at", "updated_at", "deleted_at"]
    ordering = ["-id"]

    fieldsets = (
        ("Import", {"fields": ("import_officiel", "numero_ligne_import")}),
        ("Concours", {"fields": ("numero_recepisse", "specialite", "centre_composition", "region_composition", "province_composition")}),
        ("Identité", {"fields": ("nom", "prenoms", "nom_et_prenoms", "sexe", "date_naissance", "lieu_naissance", "nationalite", "numero_cnib")}),
        ("Contacts", {"fields": ("telephone", "email", "contact_urgence", "nom_contact_urgence")}),
        ("Validation", {"fields": ("statut_validation", "donnees_brutes", "donnees_normalisees")}),
        ("Suivi", {"fields": ("created_at", "updated_at", "deleted_at")}),
    )


@admin.register(ImmergeSelectionne)
class ImmergeSelectionneAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "matricule",
        "reference_selection",
        "identite_affichable",
        "sexe",
        "structure_origine",
        "statut_validation",
    ]
    list_filter = ["statut_validation", "region_structure", "province_structure", "deleted_at"]
    search_fields = ["matricule", "reference_selection", "nom", "prenoms", "nom_et_prenoms", "numero_cnib", "telephone", "email", "structure_origine"]
    readonly_fields = ["created_at", "updated_at", "deleted_at"]
    ordering = ["-id"]

    fieldsets = (
        ("Import", {"fields": ("import_officiel", "numero_ligne_import")}),
        ("Sélection", {"fields": ("matricule", "reference_selection", "structure_origine", "motif_selection", "region_structure", "province_structure")}),
        ("Identité", {"fields": ("nom", "prenoms", "nom_et_prenoms", "sexe", "date_naissance", "lieu_naissance", "nationalite", "numero_cnib")}),
        ("Contacts", {"fields": ("telephone", "email", "contact_urgence", "nom_contact_urgence")}),
        ("Validation", {"fields": ("statut_validation", "donnees_brutes", "donnees_normalisees")}),
        ("Suivi", {"fields": ("created_at", "updated_at", "deleted_at")}),
    )


@admin.register(InscriptionVolontaire)
class InscriptionVolontaireAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "code_suivi",
        "identite_affichable",
        "telephone",
        "email",
        "region_residence",
        "statut_demande",
        "date_soumission",
    ]
    list_filter = ["statut_demande", "session", "region_residence", "province_residence", "deleted_at"]
    search_fields = ["code_suivi", "nom", "prenoms", "nom_et_prenoms", "numero_cnib", "telephone", "email"]
    readonly_fields = ["created_at", "updated_at", "deleted_at"]
    ordering = ["-date_soumission", "-id"]

    fieldsets = (
        ("Session", {"fields": ("session", "code_suivi")}),
        ("Identité", {"fields": ("nom", "prenoms", "nom_et_prenoms", "sexe", "date_naissance", "lieu_naissance", "nationalite", "numero_cnib")}),
        ("Contacts", {"fields": ("telephone", "email", "contact_urgence", "nom_contact_urgence")}),
        ("Résidence", {"fields": ("region_residence", "province_residence", "commune_residence", "adresse_residence")}),
        ("Profil", {"fields": ("niveau_etude", "profession", "motivation")}),
        ("Décision", {"fields": ("statut_demande", "date_decision", "motif_decision")}),
        ("Données", {"fields": ("donnees_brutes",)}),
        ("Suivi", {"fields": ("date_soumission", "created_at", "updated_at", "deleted_at")}),
    )


@admin.register(Immerge)
class ImmergeAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "code_fasoim",
        "type_immerge",
        "origine_id",
        "session",
        "statut",
        "date_creation_code",
    ]
    list_filter = ["type_immerge", "statut", "session", "deleted_at"]
    search_fields = ["code_fasoim", "qr_code", "origine_id"]
    readonly_fields = ["created_at", "updated_at", "deleted_at"]
    ordering = ["-id"]

    fieldsets = (
        ("Session", {"fields": ("session",)}),
        ("Source", {"fields": ("type_immerge", "origine_id")}),
        ("Code FasoIM", {"fields": ("code_fasoim", "qr_code", "date_creation_code")}),
        ("Statut", {"fields": ("statut",)}),
        ("Suivi", {"fields": ("created_at", "updated_at", "deleted_at")}),
    )
