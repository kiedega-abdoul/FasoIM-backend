from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import RestrictionMedicale, VisiteMedicale


class RestrictionMedicaleInline(admin.StackedInline):
    model = RestrictionMedicale
    extra = 0

    fields = (
        "libelle",
        "type_restriction",
        "modules_concernes",
        "consigne_operationnelle",
        "description_medicale",
        "niveau_sensibilite",
        "date_debut",
        "date_fin",
        "statut",
        "saisie_par",
        "date_levee",
        "motif_levee",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    readonly_fields = (
        "saisie_par",
        "date_levee",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    show_change_link = True


@admin.register(VisiteMedicale)
class VisiteMedicaleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "code_fasoim",
        "centre",
        "resultat",
        "statut",
        "statut_application",
        "date_visite",
        "agent_sante",
    )

    list_filter = (
        "resultat",
        "statut",
        "statut_application",
        "session",
        "centre",
        "date_visite",
        "est_courante",
    )

    search_fields = (
        "affectation_centre__immerge__code_fasoim",
        "affectation_centre__immerge__matricule_fasoim",
        "centre__code",
        "centre__nom",
        "agent_sante__username",
        "agent_sante__email",
    )

    ordering = (
        "-date_visite",
        "-id",
    )

    date_hierarchy = "date_visite"

    list_select_related = (
        "affectation_centre",
        "affectation_centre__immerge",
        "session",
        "centre",
        "agent_sante",
    )

    raw_id_fields = (
        "affectation_centre",
        "agent_sante",
    )

    readonly_fields = (
        "session",
        "centre",
        "date_validation",
        "statut_application",
        "date_application",
        "erreur_application",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    fieldsets = (
        (
            "Immergé et visite",
            {
                "fields": (
                    "affectation_centre",
                    "session",
                    "centre",
                    "numero_visite",
                    "est_courante",
                    "date_visite",
                    "resultat",
                    "statut",
                    "agent_sante",
                    "date_validation",
                )
            },
        ),
        (
            "Informations médicales confidentielles",
            {
                "fields": (
                    "observations_medicales",
                    "document_medical",
                    "date_prochaine_visite",
                )
            },
        ),
        (
            "Informations opérationnelles",
            {
                "fields": (
                    "consignes_operationnelles",
                )
            },
        ),
        (
            "Application dans les autres modules",
            {
                "fields": (
                    "statut_application",
                    "date_application",
                    "erreur_application",
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
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    inlines = (
        RestrictionMedicaleInline,
    )

    actions = (
        "valider_visites_selectionnees",
    )

    @admin.display(description="Code FasoIM")
    def code_fasoim(self, obj):
        immerge = obj.affectation_centre.immerge

        return (
            getattr(immerge, "code_fasoim", None)
            or getattr(immerge, "matricule_fasoim", None)
            or immerge.id
        )

    def save_model(self, request, obj, form, change):
        if not obj.agent_sante_id:
            obj.agent_sante = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    def save_formset(
        self,
        request,
        form,
        formset,
        change,
    ):
        instances = formset.save(commit=False)

        for objet in formset.deleted_objects:
            objet.delete()

        for objet in instances:
            if (
                isinstance(objet, RestrictionMedicale)
                and not objet.saisie_par_id
            ):
                objet.saisie_par = request.user

            objet.save()

        formset.save_m2m()

    @admin.action(
        description="Valider les visites sélectionnées"
    )
    def valider_visites_selectionnees(
        self,
        request,
        queryset,
    ):
        validees = 0
        erreurs = 0

        for visite in queryset:
            try:
                visite.valider(
                    agent_sante=request.user,
                )
                validees += 1

            except ValidationError as exception:
                erreurs += 1

                self.message_user(
                    request,
                    f"Visite {visite.id} : {exception}",
                    level=messages.ERROR,
                )

        if validees:
            self.message_user(
                request,
                f"{validees} visite(s) validée(s).",
                level=messages.SUCCESS,
            )

        if erreurs:
            self.message_user(
                request,
                f"{erreurs} visite(s) non validée(s).",
                level=messages.WARNING,
            )


@admin.register(RestrictionMedicale)
class RestrictionMedicaleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "libelle",
        "code_fasoim",
        "type_restriction",
        "modules",
        "statut",
        "date_debut",
        "date_fin",
        "saisie_par",
    )

    list_filter = (
        "type_restriction",
        "statut",
        "niveau_sensibilite",
        "date_debut",
        "date_fin",
    )

    search_fields = (
        "libelle",
        "consigne_operationnelle",
        (
            "visite_medicale__affectation_centre"
            "__immerge__code_fasoim"
        ),
        (
            "visite_medicale__affectation_centre"
            "__immerge__matricule_fasoim"
        ),
        "visite_medicale__centre__code",
        "visite_medicale__centre__nom",
    )

    ordering = (
        "-date_debut",
        "-id",
    )

    date_hierarchy = "date_debut"

    raw_id_fields = (
        "visite_medicale",
        "saisie_par",
    )

    list_select_related = (
        "visite_medicale",
        "visite_medicale__affectation_centre",
        "visite_medicale__affectation_centre__immerge",
        "saisie_par",
    )

    readonly_fields = (
        "date_levee",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    fieldsets = (
        (
            "Restriction",
            {
                "fields": (
                    "visite_medicale",
                    "libelle",
                    "type_restriction",
                    "modules_concernes",
                    "consigne_operationnelle",
                    "date_debut",
                    "date_fin",
                    "statut",
                )
            },
        ),
        (
            "Informations médicales confidentielles",
            {
                "fields": (
                    "description_medicale",
                    "niveau_sensibilite",
                )
            },
        ),
        (
            "Levée et traçabilité",
            {
                "fields": (
                    "saisie_par",
                    "date_levee",
                    "motif_levee",
                    "created_at",
                    "updated_at",
                    "deleted_at",
                )
            },
        ),
    )

    actions = (
        "lever_restrictions_selectionnees",
        "expirer_restrictions_selectionnees",
    )

    @admin.display(description="Code FasoIM")
    def code_fasoim(self, obj):
        immerge = (
            obj.visite_medicale
            .affectation_centre
            .immerge
        )

        return (
            getattr(immerge, "code_fasoim", None)
            or getattr(immerge, "matricule_fasoim", None)
            or immerge.id
        )

    @admin.display(description="Modules")
    def modules(self, obj):
        return ", ".join(
            obj.modules_concernes or []
        )

    def save_model(self, request, obj, form, change):
        if not obj.saisie_par_id:
            obj.saisie_par = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    @admin.action(
        description="Lever les restrictions sélectionnées"
    )
    def lever_restrictions_selectionnees(
        self,
        request,
        queryset,
    ):
        total = 0

        for restriction in queryset:
            restriction.lever(
                motif=(
                    "Levée depuis l'administration."
                ),
                levee_par=request.user,
            )
            total += 1

        self.message_user(
            request,
            f"{total} restriction(s) levée(s).",
            level=messages.SUCCESS,
        )

    @admin.action(
        description=(
            "Expirer les restrictions arrivées à terme"
        )
    )
    def expirer_restrictions_selectionnees(
        self,
        request,
        queryset,
    ):
        total = 0

        for restriction in queryset:
            ancien_statut = restriction.statut

            restriction.expirer_si_necessaire()

            if restriction.statut != ancien_statut:
                total += 1

        self.message_user(
            request,
            f"{total} restriction(s) expirée(s).",
            level=messages.SUCCESS,
        )