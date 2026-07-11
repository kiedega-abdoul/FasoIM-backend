from django.contrib import admin, messages

from .models import ArticleKit, RemiseKit


@admin.register(ArticleKit)
class ArticleKitAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "designation",
        "type_kit",
        "session",
        "portee",
        "quantite_affichee",
        "obligatoire",
        "ordre",
        "statut",
    )
    list_filter = (
        "type_kit",
        "statut",
        "obligatoire",
        "session",
        "centre",
    )
    search_fields = (
        "designation",
        "description",
        "session__code",
        "session__nom",
        "centre__code",
        "centre__nom",
    )
    ordering = (
        "session_id",
        "centre_id",
        "ordre",
        "designation",
    )
    raw_id_fields = (
        "session",
        "centre",
    )
    list_select_related = (
        "session",
        "centre",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
    )
    fieldsets = (
        (
            "Périmètre",
            {
                "fields": (
                    "session",
                    "centre",
                )
            },
        ),
        (
            "Article",
            {
                "fields": (
                    "designation",
                    "description",
                    "type_kit",
                    "quantite",
                    "unite",
                    "obligatoire",
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
    actions = (
        "activer_articles",
        "desactiver_articles",
    )

    @admin.display(description="Portée")
    def portee(self, obj):
        return obj.centre.nom if obj.centre_id else "Tous les centres"

    @admin.display(description="Quantité")
    def quantite_affichee(self, obj):
        return f"{obj.quantite} {obj.unite}"

    @admin.action(description="Activer les articles sélectionnés")
    def activer_articles(self, request, queryset):
        total = 0

        for article in queryset:
            if article.deleted_at is None:
                article.reactiver()
                total += 1

        self.message_user(
            request,
            f"{total} article(s) activé(s).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Désactiver les articles sélectionnés")
    def desactiver_articles(self, request, queryset):
        total = 0

        for article in queryset:
            article.desactiver()
            total += 1

        self.message_user(
            request,
            f"{total} article(s) désactivé(s).",
            level=messages.SUCCESS,
        )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RemiseKit)
class RemiseKitAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "code_fasoim",
        "article_kit",
        "centre",
        "quantites",
        "statut_remise",
        "date_remise",
        "remis_par",
    )
    list_filter = (
        "statut_remise",
        "date_remise",
        "article_kit__session",
        "affectation_centre__centre",
    )
    search_fields = (
        "affectation_centre__immerge__code_fasoim",
        "article_kit__designation",
        "affectation_centre__centre__code",
        "affectation_centre__centre__nom",
        "remis_par__username",
        "remis_par__email",
    )
    ordering = (
        "-date_remise",
        "-id",
    )
    date_hierarchy = "date_remise"
    raw_id_fields = (
        "affectation_centre",
        "article_kit",
        "remis_par",
    )
    list_select_related = (
        "affectation_centre",
        "affectation_centre__immerge",
        "affectation_centre__centre",
        "article_kit",
        "remis_par",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
    )
    fieldsets = (
        (
            "Bénéficiaire et article",
            {
                "fields": (
                    "affectation_centre",
                    "article_kit",
                )
            },
        ),
        (
            "Remise",
            {
                "fields": (
                    "quantite_prevue",
                    "quantite_remise",
                    "statut_remise",
                    "observations",
                    "remis_par",
                    "date_remise",
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

    @admin.display(description="Code FasoIM")
    def code_fasoim(self, obj):
        immerge = obj.affectation_centre.immerge
        return (
            getattr(immerge, "code_fasoim", None)
            or immerge.id
        )

    @admin.display(description="Centre")
    def centre(self, obj):
        return obj.affectation_centre.centre.nom

    @admin.display(description="Quantités")
    def quantites(self, obj):
        return (
            f"{obj.quantite_remise} / "
            f"{obj.quantite_prevue}"
        )

    def save_model(self, request, obj, form, change):
        if not obj.remis_par_id:
            obj.remis_par = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    def has_delete_permission(self, request, obj=None):
        return False
