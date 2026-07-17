from __future__ import annotations

from rest_framework import serializers

from .models import DocumentGenere, PublicationOfficielle, ResultatFinal


class ResultatFinalSerializer(serializers.ModelSerializer):
    code_fasoim = serializers.CharField(source="immerge.code_fasoim", read_only=True)
    centre_nom = serializers.CharField(source="centre.nom", read_only=True)
    region_nom = serializers.CharField(source="region.nom", read_only=True)
    decision_libelle = serializers.CharField(source="get_decision_display", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)

    class Meta:
        model = ResultatFinal
        fields = [
            "id", "session", "region", "region_nom", "centre", "centre_nom",
            "affectation_centre", "immerge", "code_fasoim",
            "total_seances", "total_eligible_presence", "presences_favorables",
            "presents", "retards", "absences", "excuses", "dispenses_presence",
            "taux_presence", "seuil_presence", "evaluation_active",
            "evaluations_applicables", "evaluations_cloturees", "notes_comptees",
            "absences_evaluation", "dispenses_evaluation", "somme_coefficients",
            "moyenne_sur_20", "seuil_moyenne_sur_20",
            "visite_medicale_active", "statut_medical_administratif",
            "participation_medicale_autorisee", "incident_bloquant",
            "decision", "decision_libelle", "motifs", "statut", "statut_libelle",
            "version", "date_calcul", "date_validation_centre",
            "date_validation_region", "date_publication",
        ]
        read_only_fields = fields


class PublicationOfficielleSerializer(serializers.ModelSerializer):
    session_nom = serializers.CharField(source="session.nom", read_only=True)
    region_nom = serializers.CharField(source="region.nom", read_only=True, allow_null=True)
    centre_nom = serializers.CharField(source="centre.nom", read_only=True, allow_null=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    type_libelle = serializers.CharField(source="get_type_publication_display", read_only=True)

    class Meta:
        model = PublicationOfficielle
        fields = [
            "id", "uuid_publication", "reference", "type_publication", "type_libelle",
            "perimetre", "session", "session_nom", "region", "region_nom",
            "centre", "centre_nom", "version", "statut", "statut_libelle",
            "resume", "commentaire", "motif_correction", "preparee_par",
            "soumise_par", "validee_region_par", "publiee_par",
            "date_soumission", "date_validation_region", "date_publication",
        ]
        read_only_fields = fields


class DocumentGenereSerializer(serializers.ModelSerializer):
    session_nom = serializers.CharField(source="session.nom", read_only=True)
    region_nom = serializers.CharField(source="region.nom", read_only=True, allow_null=True)
    centre_nom = serializers.CharField(source="centre.nom", read_only=True, allow_null=True)
    code_fasoim = serializers.CharField(source="immerge.code_fasoim", read_only=True, allow_null=True)
    type_libelle = serializers.CharField(source="get_type_document_display", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    telechargeable = serializers.BooleanField(source="est_telechargeable", read_only=True)

    class Meta:
        model = DocumentGenere
        fields = [
            "id", "uuid_document", "type_document", "type_libelle", "format_fichier",
            "titre", "numero_document", "session", "session_nom", "region", "region_nom",
            "centre", "centre_nom", "immerge", "code_fasoim", "resultat_final",
            "publication", "nom_fichier", "type_mime", "taille_octets", "hash_sha256",
            "code_verification", "version", "statut", "statut_libelle", "visibilite",
            "resume_generation", "message_erreur", "signataire",
            "nom_signataire_snapshot", "fonction_signataire_snapshot",
            "organisation_signataire_snapshot", "signature_appliquee", "cachet_applique",
            "date_generation", "date_signature", "date_publication", "telechargeable",
        ]
        read_only_fields = fields


class CentreActionSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)


class ImmergeActionSerializer(serializers.Serializer):
    immerge_id = serializers.IntegerField(min_value=1)


class RejetPublicationSerializer(serializers.Serializer):
    motif = serializers.CharField(min_length=3, max_length=2000)


class PublierSessionSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    type_publication = serializers.ChoiceField(choices=PublicationOfficielle.TypePublication.choices)


class GenererRapportSerializer(serializers.Serializer):
    type_document = serializers.ChoiceField(
        choices=[
            choix for choix in DocumentGenere.TypeDocument.choices
            if choix[0] not in {
                DocumentGenere.TypeDocument.ATTESTATION,
                DocumentGenere.TypeDocument.FICHE_ARRIVEE,
            }
        ]
    )
    format_fichier = serializers.ChoiceField(choices=DocumentGenere.Format.choices)
    session_id = serializers.IntegerField(min_value=1)
    region_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    centre_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    parametres = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        if attrs.get("centre_id") and attrs.get("region_id"):
            raise serializers.ValidationError("Choisissez un centre ou une région, pas les deux.")
        if not isinstance(attrs.get("parametres", {}), dict):
            raise serializers.ValidationError({"parametres": "Un objet JSON est attendu."})
        return attrs


class ConsultationArriveeSerializer(serializers.Serializer):
    code_fasoim = serializers.CharField(required=False, allow_blank=True, max_length=80)
    type_immerge = serializers.CharField(required=False, allow_blank=True, max_length=30)
    identifiant = serializers.CharField(required=False, allow_blank=True, max_length=150)
    session_code = serializers.CharField(required=False, allow_blank=True, max_length=80)
    date_naissance = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs.get("code_fasoim"):
            return attrs
        requis = ["type_immerge", "identifiant", "session_code", "date_naissance"]
        manquants = [champ for champ in requis if not attrs.get(champ)]
        if manquants:
            raise serializers.ValidationError({champ: "Ce champ est obligatoire." for champ in manquants})
        return attrs


class VerificationAttestationSerializer(serializers.Serializer):
    code = serializers.CharField(required=False, allow_blank=True, max_length=100)
    numero = serializers.CharField(required=False, allow_blank=True, max_length=160)

    def validate(self, attrs):
        if bool(attrs.get("code")) == bool(attrs.get("numero")):
            raise serializers.ValidationError("Fournissez le code de vérification ou le numéro, mais pas les deux.")
        return attrs


class ProgressionDocumentSerializer(serializers.Serializer):
    task_id = serializers.UUIDField()


class ValidationAttestationsLotSerializer(serializers.Serializer):
    publication_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=500,
    )


class StatistiquesAttestationsRegionSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    region_id = serializers.IntegerField(min_value=1, required=False)
