from __future__ import annotations

from rest_framework import serializers

from accounts.service import ControleAccesService

from .models import JournalAction


class JournalActionListeSerializer(serializers.ModelSerializer):
    origine_libelle = serializers.CharField(source="get_origine_display", read_only=True)
    resultat_libelle = serializers.CharField(source="get_resultat_display", read_only=True)
    acteur_nom = serializers.SerializerMethodField()
    immerge_reference = serializers.SerializerMethodField()

    class Meta:
        model = JournalAction
        fields = [
            "id",
            "uuid_evenement",
            "created_at",
            "origine",
            "origine_libelle",
            "resultat",
            "resultat_libelle",
            "canal",
            "code_action",
            "module_source",
            "acteur",
            "acteur_nom",
            "immerge",
            "immerge_reference",
            "session",
            "region",
            "centre",
            "objet_type",
            "objet_id",
            "objet_reference",
            "motif",
        ]
        read_only_fields = fields

    def get_acteur_nom(self, obj):
        if not obj.acteur:
            return ""
        return obj.acteur.nom_complet or obj.acteur.username

    def get_immerge_reference(self, obj):
        if not obj.immerge:
            return ""
        return getattr(obj.immerge, "code_fasoim", "") or str(obj.immerge_id)


class JournalActionDetailSerializer(JournalActionListeSerializer):
    class Meta(JournalActionListeSerializer.Meta):
        fields = JournalActionListeSerializer.Meta.fields + [
            "contexte",
            "adresse_ip",
            "user_agent",
            "methode_http",
            "chemin_api",
            "statut_http",
            "duree_ms",
            "task_id",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        donnees = super().to_representation(instance)
        request = self.context.get("request")
        acteur = getattr(request, "user", None)
        autorise_securite = bool(getattr(acteur, "is_superuser", False))
        if acteur and not autorise_securite:
            region_code = (
                instance.region.code
                if instance.region_id
                else (instance.centre.region.code if instance.centre_id else None)
            )
            autorise_securite = ControleAccesService.acteur_peut(
                acteur,
                "consulter_audit_securite",
                session_id=instance.session_id,
                region_code=region_code,
                centre_id=instance.centre_id,
            ).autorise
        if not autorise_securite:
            for champ in ("adresse_ip", "user_agent", "chemin_api", "task_id"):
                donnees.pop(champ, None)
        return donnees


class DemandeExportAuditSerializer(serializers.Serializer):
    FORMAT_CHOICES = (("CSV", "CSV"), ("XLSX", "Excel XLSX"))

    format = serializers.ChoiceField(choices=FORMAT_CHOICES, default="CSV")
    date_debut = serializers.DateTimeField(required=False)
    date_fin = serializers.DateTimeField(required=False)
    origine = serializers.ChoiceField(choices=JournalAction.Origine.choices, required=False)
    resultat = serializers.ChoiceField(choices=JournalAction.Resultat.choices, required=False)
    canal = serializers.ChoiceField(choices=JournalAction.Canal.choices, required=False)
    module = serializers.CharField(max_length=80, required=False)
    code_action = serializers.CharField(max_length=140, required=False)
    acteur = serializers.IntegerField(min_value=1, required=False)
    immerge = serializers.IntegerField(min_value=1, required=False)
    session = serializers.IntegerField(min_value=1, required=False)
    region = serializers.IntegerField(min_value=1, required=False)
    centre = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs):
        if attrs.get("date_debut") and attrs.get("date_fin"):
            if attrs["date_fin"] < attrs["date_debut"]:
                raise serializers.ValidationError("La date de fin doit suivre la date de début.")
        return attrs
