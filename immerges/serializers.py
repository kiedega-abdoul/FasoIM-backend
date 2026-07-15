from __future__ import annotations

from rest_framework import serializers

from sessions_app.models import SessionImmersion

from .models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
)
from .service import (
    ImmergeConcoursService,
    ImmergeExamenService,
    ImmergeSelectionneService,
    ImmergeService,
    ImmergeSourceResolverService,
    InscriptionVolontaireService,
)


class SourceIdentiteSerializerMixin:
    champs_identite = [
        "nom",
        "prenoms",
        "nom_et_prenoms",
        "sexe",
        "date_naissance",
        "lieu_naissance",
        "nationalite",
        "numero_cnib",
        "telephone",
        "email",
        "contact_urgence",
        "nom_contact_urgence",
    ]


class ImmergeExamenSerializer(SourceIdentiteSerializerMixin, serializers.ModelSerializer):
    identite_affichable = serializers.CharField(read_only=True)

    class Meta:
        model = ImmergeExamen
        fields = [
            "id",
            "import_officiel",
            "numero_ligne_import",
            "numero_pv",
            "type_examen",
            "serie",
            "annee_obtention",
            "statut",
            *SourceIdentiteSerializerMixin.champs_identite,
            "centre_examen",
            "etablissement_origine",
            "region_examen",
            "province_examen",
            "statut_validation",
            "donnees_brutes",
            "donnees_normalisees",
            "identite_affichable",
        ]
        read_only_fields = ["id", "identite_affichable"]

    def create(self, validated_data):
        return ImmergeExamenService.creer(**validated_data)

    def update(self, instance, validated_data):
        return ImmergeExamenService.modifier(instance, **validated_data)


class ImmergeConcoursSerializer(SourceIdentiteSerializerMixin, serializers.ModelSerializer):
    identite_affichable = serializers.CharField(read_only=True)

    class Meta:
        model = ImmergeConcours
        fields = [
            "id",
            "import_officiel",
            "numero_ligne_import",
            "numero_recepisse",
            *SourceIdentiteSerializerMixin.champs_identite,
            "specialite",
            "centre_composition",
            "region_composition",
            "province_composition",
            "statut_validation",
            "donnees_brutes",
            "donnees_normalisees",
            "identite_affichable",
        ]
        read_only_fields = ["id", "identite_affichable"]

    def create(self, validated_data):
        return ImmergeConcoursService.creer(**validated_data)

    def update(self, instance, validated_data):
        return ImmergeConcoursService.modifier(instance, **validated_data)


class ImmergeSelectionneSerializer(SourceIdentiteSerializerMixin, serializers.ModelSerializer):
    identite_affichable = serializers.CharField(read_only=True)

    class Meta:
        model = ImmergeSelectionne
        fields = [
            "id",
            "import_officiel",
            "numero_ligne_import",
            "matricule",
            "reference_selection",
            *SourceIdentiteSerializerMixin.champs_identite,
            "structure_origine",
            "motif_selection",
            "region_structure",
            "province_structure",
            "statut_validation",
            "donnees_brutes",
            "donnees_normalisees",
            "identite_affichable",
        ]
        read_only_fields = ["id", "identite_affichable"]

    def create(self, validated_data):
        return ImmergeSelectionneService.creer(**validated_data)

    def update(self, instance, validated_data):
        return ImmergeSelectionneService.modifier(instance, **validated_data)


class InscriptionVolontaireSerializer(serializers.ModelSerializer):
    identite_affichable = serializers.CharField(read_only=True)
    acceptable = serializers.SerializerMethodField()
    blocages_acceptation = serializers.SerializerMethodField()
    session_nom = serializers.CharField(source="session.nom", read_only=True)
    session_code = serializers.CharField(source="session.code", read_only=True)
    session_annee = serializers.IntegerField(source="session.annee", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_demande_display", read_only=True)

    class Meta:
        model = InscriptionVolontaire
        fields = [
            "id",
            "session",
            "session_nom",
            "session_code",
            "session_annee",
            "statut_libelle",
            "acceptable",
            "blocages_acceptation",
            "code_suivi",
            "nom",
            "prenoms",
            "nom_et_prenoms",
            "sexe",
            "date_naissance",
            "lieu_naissance",
            "nationalite",
            "numero_cnib",
            "telephone",
            "email",
            "contact_urgence",
            "nom_contact_urgence",
            "region_residence",
            "province_residence",
            "commune_residence",
            "adresse_residence",
            "niveau_etude",
            "profession",
            "motivation",
            "statut_demande",
            "date_soumission",
            "date_decision",
            "motif_decision",
            "donnees_brutes",
            "identite_affichable",
        ]
        read_only_fields = [
            "id",
            "code_suivi",
            "statut_demande",
            "date_soumission",
            "date_decision",
            "motif_decision",
            "identite_affichable",
            "acceptable",
            "blocages_acceptation",
        ]

    def get_acceptable(self, obj):
        return InscriptionVolontaireService.verifier_acceptabilite(obj)["acceptable"]

    def get_blocages_acceptation(self, obj):
        return InscriptionVolontaireService.verifier_acceptabilite(obj)["blocages"]

    def create(self, validated_data):
        return InscriptionVolontaireService.creer(**validated_data)

    def update(self, instance, validated_data):
        return InscriptionVolontaireService.modifier(instance, **validated_data)


class InscriptionVolontairePubliqueSerializer(serializers.ModelSerializer):
    """Données strictement nécessaires à une soumission publique."""

    session_id = serializers.PrimaryKeyRelatedField(
        source="session",
        queryset=SessionImmersion.objects.filter(deleted_at__isnull=True),
        write_only=True,
    )

    class Meta:
        model = InscriptionVolontaire
        fields = [
            "session_id",
            "nom",
            "prenoms",
            "sexe",
            "date_naissance",
            "lieu_naissance",
            "nationalite",
            "numero_cnib",
            "telephone",
            "email",
            "contact_urgence",
            "nom_contact_urgence",
            "region_residence",
            "province_residence",
            "commune_residence",
            "adresse_residence",
            "niveau_etude",
            "profession",
            "motivation",
        ]
        extra_kwargs = {
            "nom": {"required": True, "allow_blank": False},
            "prenoms": {"required": True, "allow_blank": False},
            "sexe": {"required": True, "allow_blank": False},
            "date_naissance": {"required": True, "allow_null": False},
            "lieu_naissance": {"required": True, "allow_blank": False},
            "nationalite": {"required": True, "allow_blank": False},
            "numero_cnib": {"required": True, "allow_blank": False},
            "telephone": {"required": True, "allow_blank": False},
            "email": {"required": True, "allow_blank": False},
            "contact_urgence": {"required": True, "allow_blank": False},
            "nom_contact_urgence": {"required": True, "allow_blank": False},
            "region_residence": {"required": True, "allow_blank": False},
            "province_residence": {"required": True, "allow_blank": False},
            "commune_residence": {"required": False, "allow_blank": True},
            "adresse_residence": {"required": True, "allow_blank": False},
            "niveau_etude": {"required": False, "allow_blank": True},
            "profession": {"required": True, "allow_blank": False},
            "motivation": {"required": True, "allow_blank": False},
        }

    def validate_date_naissance(self, valeur):
        from django.utils import timezone

        if valeur > timezone.localdate():
            raise serializers.ValidationError("La date de naissance ne peut pas être dans le futur.")
        return valeur

    def create(self, validated_data):
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            return InscriptionVolontaireService.creer_publiquement(**validated_data)
        except DjangoValidationError as exc:
            detail = getattr(exc, "message_dict", None) or {"detail": exc.messages}
            raise serializers.ValidationError(detail) from exc


class SuiviVolontairePublicSerializer(serializers.Serializer):
    """Réponse publique minimale pour le suivi d'une demande volontaire."""

    code_suivi = serializers.CharField()
    nom_complet = serializers.CharField()
    session = serializers.CharField()
    statut = serializers.CharField()
    statut_libelle = serializers.CharField()
    date_soumission = serializers.DateTimeField()
    date_decision = serializers.DateTimeField(allow_null=True)
    motif_decision = serializers.CharField(allow_blank=True)
    code_fasoim = serializers.CharField(allow_blank=True)
    message = serializers.CharField()


class InscriptionVolontaireDecisionSerializer(serializers.Serializer):
    motif_decision = serializers.CharField(required=False, allow_blank=True)
    creer_immerge = serializers.BooleanField(default=True)


class SourceResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    identite_affichable = serializers.CharField()
    telephone = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    reference = serializers.CharField(required=False, allow_blank=True)


class ImmergeSerializer(serializers.ModelSerializer):
    source_resume = serializers.SerializerMethodField()

    class Meta:
        model = Immerge
        fields = [
            "id",
            "session",
            "type_immerge",
            "origine_id",
            "code_fasoim",
            "qr_code",
            "statut",
            "date_creation_code",
            "source_resume",
        ]
        read_only_fields = ["id", "code_fasoim", "qr_code", "date_creation_code", "source_resume"]

    def get_source_resume(self, obj):
        try:
            source = ImmergeSourceResolverService.recuperer(obj)
        except Exception:
            return None
        reference = ""
        for champ in ["numero_pv", "numero_recepisse", "matricule", "reference_selection", "code_suivi"]:
            valeur = getattr(source, champ, "")
            if valeur:
                reference = valeur
                break
        return {
            "id": source.id,
            "identite_affichable": getattr(source, "identite_affichable", ""),
            "telephone": getattr(source, "telephone", ""),
            "email": getattr(source, "email", ""),
            "reference": reference,
        }


class CentraliserSourceSerializer(serializers.Serializer):
    type_immerge = serializers.ChoiceField(choices=Immerge.TypeImmerge.choices)
    source_id = serializers.IntegerField(min_value=1)

    def save(self, **kwargs):
        type_immerge = self.validated_data["type_immerge"]
        source_id = self.validated_data["source_id"]

        if type_immerge in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
            from .repository import ImmergeExamenRepository

            source = ImmergeExamenRepository.get_by_id(source_id)
            return ImmergeService.creer_depuis_source(type_immerge=type_immerge, source=source)
        if type_immerge == Immerge.TypeImmerge.CONCOURS:
            from .repository import ImmergeConcoursRepository

            source = ImmergeConcoursRepository.get_by_id(source_id)
            return ImmergeService.creer_depuis_concours(source)
        if type_immerge == Immerge.TypeImmerge.SELECTIONNE:
            from .repository import ImmergeSelectionneRepository

            source = ImmergeSelectionneRepository.get_by_id(source_id)
            return ImmergeService.creer_depuis_selectionne(source)
        if type_immerge == Immerge.TypeImmerge.VOLONTAIRE:
            from .repository import InscriptionVolontaireRepository

            source = InscriptionVolontaireRepository.get_by_id(source_id)
            return ImmergeService.creer_depuis_volontaire(source)
        raise serializers.ValidationError({"type_immerge": "Type d'immergé non pris en charge."})


class ChangerStatutImmergeSerializer(serializers.Serializer):
    statut = serializers.ChoiceField(choices=Immerge.Statut.choices)
