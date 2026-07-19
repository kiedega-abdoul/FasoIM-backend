from django.contrib import admin

from .models import JournalAction


@admin.register(JournalAction)
class JournalActionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "code_action",
        "module_source",
        "origine",
        "resultat",
        "acteur",
        "immerge",
        "session",
        "region",
        "centre",
    )
    list_filter = ("origine", "resultat", "canal", "module_source", "created_at")
    search_fields = (
        "code_action",
        "motif",
        "objet_type",
        "objet_reference",
        "acteur__username",
        "acteur__email",
    )
    readonly_fields = tuple(champ.name for champ in JournalAction._meta.fields)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
