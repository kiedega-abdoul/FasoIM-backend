from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import (
    DemandeRavitaillementCentre,
    LigneBesoinDenree,
    RepasJournalier,
    SuiviRepas,
)


class SessionRepasResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    nom = serializers.CharField()


class CentreRepasResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    nom = serializers.CharField()


class ActeurRepasResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)


class LigneBesoinDenreeSerializer(serializers.ModelSerializer):
    demande_ravitaillement_id = serializers.IntegerField(read_only=True)
    statut_libelle = serializers.CharField(
        source="get_statut_display", read_only=True
    )

    class Meta:
        model = LigneBesoinDenree
        fields = [
            "id", "demande_ravitaillement_id", "code_denree", "designation",
            "conditionnement", "contenance_conditionnement", "unite_base",
            "quantite_demandee", "quantite_validee", "quantite_recue",
            "observations", "statut", "statut_libelle", "created_at", "updated_at",
        ]


class DemandeRavitaillementSerializer(serializers.ModelSerializer):
    session = SessionRepasResumeSerializer(read_only=True)
    centre = CentreRepasResumeSerializer(read_only=True)
    soumis_par = ActeurRepasResumeSerializer(read_only=True, allow_null=True)
    valide_par = ActeurRepasResumeSerializer(read_only=True, allow_null=True)
    lignes_denrees = serializers.SerializerMethodField()
    statut_libelle = serializers.CharField(
        source="get_statut_display", read_only=True
    )
    est_modifiable = serializers.BooleanField(read_only=True)

    class Meta:
        model = DemandeRavitaillementCentre
        fields = [
            "id", "session", "centre", "effectif_reference", "statut",
            "statut_libelle", "observations", "soumis_par", "date_soumission",
            "valide_par", "date_validation", "est_modifiable", "lignes_denrees",
            "created_at", "updated_at",
        ]

    def get_lignes_denrees(self, obj):
        lignes = obj.lignes_denrees.filter(deleted_at__isnull=True)
        return LigneBesoinDenreeSerializer(lignes, many=True).data


class DemandeRavitaillementCreateSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    observations = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class DemandeRavitaillementUpdateSerializer(serializers.Serializer):
    observations = serializers.CharField(required=False, allow_blank=True)
    recalculer_effectif = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Au moins un champ est obligatoire.")
        return attrs


class LigneBesoinDenreeInputSerializer(serializers.Serializer):
    code_denree = serializers.CharField(max_length=60)
    designation = serializers.CharField(max_length=180)
    conditionnement = serializers.CharField(max_length=80)
    contenance_conditionnement = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        required=False,
        allow_null=True,
        min_value=0,
    )
    unite_base = serializers.CharField(max_length=30)
    quantite_demandee = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )
    observations = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class LigneBesoinDenreeUpdateSerializer(LigneBesoinDenreeInputSerializer):
    code_denree = serializers.CharField(max_length=60, required=False)
    designation = serializers.CharField(max_length=180, required=False)
    conditionnement = serializers.CharField(max_length=80, required=False)
    unite_base = serializers.CharField(max_length=30, required=False)
    quantite_demandee = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Au moins un champ est obligatoire.")
        return attrs


class ValidationDemandeSerializer(serializers.Serializer):
    quantites = serializers.DictField(
        child=serializers.DecimalField(
            max_digits=14, decimal_places=3, min_value=0
        ),
        required=False,
        default=dict,
    )


class ReceptionDenreeSerializer(serializers.Serializer):
    quantite_recue = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=0
    )


class FiltreDemandeSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=False, min_value=1)
    region_id = serializers.IntegerField(required=False, min_value=1)
    centre_id = serializers.IntegerField(required=False, min_value=1)
    statut = serializers.ChoiceField(
        choices=DemandeRavitaillementCentre.Statut.choices, required=False
    )
    recherche = serializers.CharField(required=False, allow_blank=False)


class FiltreLigneDenreeSerializer(serializers.Serializer):
    demande_id = serializers.IntegerField(required=False, min_value=1)
    statut = serializers.ChoiceField(
        choices=LigneBesoinDenree.Statut.choices, required=False
    )
    recherche = serializers.CharField(required=False, allow_blank=False)


class RepasJournalierSerializer(serializers.ModelSerializer):
    demande_ravitaillement = DemandeRavitaillementSerializer(read_only=True)
    cree_par = ActeurRepasResumeSerializer(read_only=True, allow_null=True)
    valide_par = ActeurRepasResumeSerializer(read_only=True, allow_null=True)
    type_repas_libelle = serializers.CharField(
        source="get_type_repas_display", read_only=True
    )
    statut_libelle = serializers.CharField(
        source="get_statut_display", read_only=True
    )
    statut_controle_sante_libelle = serializers.CharField(
        source="get_statut_controle_sante_display", read_only=True
    )
    total_special_prevu = serializers.IntegerField(read_only=True)
    total_prepare = serializers.IntegerField(read_only=True)

    class Meta:
        model = RepasJournalier
        fields = [
            "id", "demande_ravitaillement", "date_repas", "type_repas",
            "type_repas_libelle", "heure_prevue", "menu_prevu",
            "description_prevue", "denrees_prevues", "nombre_standard_prevu",
            "synthese_restrictions_alimentaires",
            "preparations_speciales_prevues", "total_special_prevu",
            "menu_prepare", "description_preparation_reelle",
            "denrees_reellement_utilisees", "nombre_standard_prepare",
            "preparations_speciales_reelles", "total_prepare",
            "heure_debut_preparation", "heure_fin_preparation",
            "observations_preparation", "statut_controle_sante",
            "statut_controle_sante_libelle", "date_verification_sante",
            "statut", "statut_libelle", "cree_par", "valide_par",
            "date_validation", "date_ouverture_distribution", "date_cloture",
            "motif_annulation", "created_at", "updated_at",
        ]


class RepasCreateSerializer(serializers.Serializer):
    demande_ravitaillement_id = serializers.IntegerField(min_value=1)
    date_repas = serializers.DateField()
    type_repas = serializers.ChoiceField(
        choices=RepasJournalier.TypeRepas.choices
    )
    heure_prevue = serializers.TimeField(required=False, allow_null=True)
    menu_prevu = serializers.CharField(max_length=255)
    description_prevue = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    denrees_prevues = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )
    preparations_speciales_prevues = serializers.DictField(
        child=serializers.DictField(), required=False, default=dict
    )


class RepasUpdateSerializer(RepasCreateSerializer):
    demande_ravitaillement_id = serializers.IntegerField(
        min_value=1, required=False
    )
    date_repas = serializers.DateField(required=False)
    type_repas = serializers.ChoiceField(
        choices=RepasJournalier.TypeRepas.choices, required=False
    )
    menu_prevu = serializers.CharField(max_length=255, required=False)
    denrees_prevues = serializers.ListField(
        child=serializers.DictField(), required=False
    )
    preparations_speciales_prevues = serializers.DictField(
        child=serializers.DictField(), required=False
    )

    def validate(self, attrs):
        attrs.pop("demande_ravitaillement_id", None)
        if not attrs:
            raise serializers.ValidationError("Au moins un champ est obligatoire.")
        return attrs


class PreparationReelleSerializer(serializers.Serializer):
    menu_prepare = serializers.CharField(max_length=255)
    nombre_standard_prepare = serializers.IntegerField(min_value=0)
    preparations_speciales_reelles = serializers.DictField(
        child=serializers.DictField()
    )
    description_preparation_reelle = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    denrees_reellement_utilisees = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )
    observations_preparation = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class AnnulationRepasSerializer(serializers.Serializer):
    motif = serializers.CharField(allow_blank=False)


class FiltreRepasSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=False, min_value=1)
    region_id = serializers.IntegerField(required=False, min_value=1)
    centre_id = serializers.IntegerField(required=False, min_value=1)
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(required=False)
    type_repas = serializers.ChoiceField(
        choices=RepasJournalier.TypeRepas.choices, required=False
    )
    statut = serializers.ChoiceField(
        choices=RepasJournalier.Statut.choices, required=False
    )
    statut_controle_sante = serializers.ChoiceField(
        choices=RepasJournalier.StatutControleSante.choices, required=False
    )
    recherche = serializers.CharField(required=False, allow_blank=False)

    def validate(self, attrs):
        if attrs.get("date_debut") and attrs.get("date_fin"):
            if attrs["date_fin"] < attrs["date_debut"]:
                raise serializers.ValidationError(
                    "La date de fin doit suivre la date de début."
                )
        return attrs


class AffectationSuiviResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    immerge_id = serializers.IntegerField()
    code_fasoim = serializers.CharField(source="immerge.code_fasoim")


class SuiviRepasSerializer(serializers.ModelSerializer):
    repas_journalier_id = serializers.IntegerField(read_only=True)
    groupe_id = serializers.IntegerField(read_only=True, allow_null=True)
    affectation_centre = AffectationSuiviResumeSerializer(
        read_only=True, allow_null=True
    )
    groupe_nom = serializers.CharField(
        source="groupe.nom", read_only=True, allow_null=True
    )
    type_suivi_libelle = serializers.CharField(
        source="get_type_suivi_display", read_only=True
    )
    statut_service_libelle = serializers.CharField(
        source="get_statut_service_display", read_only=True
    )

    class Meta:
        model = SuiviRepas
        fields = [
            "id", "repas_journalier_id", "type_suivi", "type_suivi_libelle",
            "groupe_id", "groupe_nom", "effectif_attendu",
            "nombre_ayant_mange", "affectation_centre",
            "categorie_alimentaire", "consigne_alimentaire",
            "preparation_speciale_prevue", "statut_service",
            "statut_service_libelle", "observation_service", "observations",
            "date_saisie", "created_at", "updated_at",
        ]


class FiltreSuiviRepasSerializer(serializers.Serializer):
    repas_id = serializers.IntegerField(required=False, min_value=1)
    type_suivi = serializers.ChoiceField(
        choices=SuiviRepas.TypeSuivi.choices, required=False
    )
    groupe_id = serializers.IntegerField(required=False, min_value=1)
    affectation_centre_id = serializers.IntegerField(required=False, min_value=1)
    statut_service = serializers.ChoiceField(
        choices=SuiviRepas.StatutService.choices, required=False
    )


class SaisieComptageSerializer(serializers.Serializer):
    nombre_ayant_mange = serializers.IntegerField(min_value=0)
    observations = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class ServiceMedicalSerializer(serializers.Serializer):
    statut_service = serializers.ChoiceField(
        choices=[
            choix for choix in SuiviRepas.StatutService.choices
            if choix[0] != SuiviRepas.StatutService.A_SERVIR
        ]
    )
    observation_service = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class LancementOperationRepasSerializer(serializers.Serializer):
    repas_id = serializers.IntegerField(min_value=1)


class ConsolidationDenreesSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    region_id = serializers.IntegerField(required=False, allow_null=True)


class RapportRepasSerializer(FiltreRepasSerializer):
    session_id = serializers.IntegerField(min_value=1)


class TacheRepasLanceeSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    operation = serializers.CharField()
    statut = serializers.CharField()
    progression = serializers.IntegerField()
    message = serializers.CharField()


class ProgressionRepasSerializer(TacheRepasLanceeSerializer):
    resultat = serializers.JSONField(required=False, allow_null=True)
    erreur = serializers.CharField(required=False, allow_blank=True)
