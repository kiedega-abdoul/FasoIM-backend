from rest_framework import serializers

from .repository import NotificationRepository
from .service import NotificationService, TypesMessage


class TestEmailSerializer(serializers.Serializer):
    sujet = serializers.CharField(max_length=255, required=False, default="Test e-mail FasoIM")
    message = serializers.CharField(
        required=False,
        default="Ceci est un e-mail de test envoyé par la plateforme FasoIM.",
    )
    cle_evenement = serializers.CharField(max_length=220, required=False, allow_blank=True, default="")


class RelancerEmailSerializer(serializers.Serializer):
    destinataire = serializers.EmailField()
    sujet = serializers.CharField(max_length=255)
    message = serializers.CharField()
    type_message = serializers.CharField(max_length=100)
    cle_evenement = serializers.CharField(max_length=220)
    acteur_id = serializers.IntegerField(required=False, allow_null=True)
    immerge_id = serializers.IntegerField(required=False, allow_null=True)
    session_id = serializers.IntegerField(required=False, allow_null=True)
    region_id = serializers.IntegerField(required=False, allow_null=True)
    centre_id = serializers.IntegerField(required=False, allow_null=True)
    objet_type = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    objet_id = serializers.IntegerField(required=False, allow_null=True)
    objet_reference = serializers.CharField(max_length=180, required=False, allow_blank=True, default="")
    version = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    contexte = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        cle = NotificationService.construire_cle(
            destinataire=attrs["destinataire"],
            type_message=attrs["type_message"],
            cle_evenement=attrs["cle_evenement"],
            objet_type=attrs.get("objet_type", ""),
            objet_id=attrs.get("objet_id"),
            version=attrs.get("version", ""),
            sujet=attrs["sujet"],
            message=attrs["message"],
        )
        if NotificationRepository.journal_succes(cle):
            raise serializers.ValidationError(
                "Cet e-mail a déjà été envoyé avec succès. Une relance créerait un doublon."
            )
        if not NotificationRepository.dernier_echec(cle):
            raise serializers.ValidationError(
                "Aucun échec antérieur correspondant ne justifie cette relance."
            )
        attrs["cle_deduplication_calculee"] = cle
        return attrs


class InformationImmergeSerializer(serializers.Serializer):
    immerge_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=10000,
    )
    type_message = serializers.CharField(max_length=100)
    sujet = serializers.CharField(max_length=255)
    message = serializers.CharField()
    cle_evenement = serializers.CharField(max_length=220)
    url_portail = serializers.URLField(required=False, allow_blank=True, default="")
    region_id = serializers.IntegerField(required=False, allow_null=True)
    centre_id = serializers.IntegerField(required=False, allow_null=True)
    contexte = serializers.JSONField(required=False, default=dict)
