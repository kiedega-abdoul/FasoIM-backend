from __future__ import annotations

from rest_framework import serializers

from affectations.models import AffectationCentre

from .models import RestrictionMedicale, VisiteMedicale


class AgentSanteResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)


class AffectationCentreSanteSerializer(serializers.ModelSerializer):
    code_fasoim = serializers.SerializerMethodField()
    type_immerge = serializers.SerializerMethodField()
    session_id = serializers.IntegerField(read_only=True)
    centre_id = serializers.IntegerField(read_only=True)
    immerge_id = serializers.IntegerField(read_only=True)
    centre_nom = serializers.CharField(
        source="centre.nom",
        read_only=True,
    )
    centre_code = serializers.CharField(
        source="centre.code",
        read_only=True,
    )

    class Meta:
        model = AffectationCentre
        fields = [
            "id",
            "immerge_id",
            "code_fasoim",
            "type_immerge",
            "session_id",
            "centre_id",
            "centre_code",
            "centre_nom",
            "statut",
            "date_affectation",
        ]

    def get_code_fasoim(self, obj):
        immerge = obj.immerge
        return (
            getattr(immerge, "code_fasoim", None)
            or getattr(immerge, "matricule_fasoim", None)
        )

    def get_type_immerge(self, obj):
        return getattr(obj.immerge, "type_immerge", None)


class RestrictionMedicaleSerializer(serializers.ModelSerializer):
    saisie_par = AgentSanteResumeSerializer(read_only=True)
    est_active = serializers.BooleanField(read_only=True)
    est_applicable = serializers.BooleanField(read_only=True)

    class Meta:
        model = RestrictionMedicale
        fields = [
            "id",
            "visite_medicale_id",
            "libelle",
            "type_restriction",
            "modules_concernes",
            "description_medicale",
            "consigne_operationnelle",
            "niveau_sensibilite",
            "date_debut",
            "date_fin",
            "statut",
            "date_levee",
            "motif_levee",
            "saisie_par",
            "est_active",
            "est_applicable",
            "created_at",
            "updated_at",
            "deleted_at",
        ]


class RestrictionOperationnelleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestrictionMedicale
        fields = [
            "id",
            "libelle",
            "type_restriction",
            "modules_concernes",
            "consigne_operationnelle",
            "date_debut",
            "date_fin",
            "statut",
        ]


class VisiteMedicaleSerializer(serializers.ModelSerializer):
    affectation_centre = AffectationCentreSanteSerializer(read_only=True)
    agent_sante = AgentSanteResumeSerializer(read_only=True)
    restrictions = RestrictionMedicaleSerializer(
        many=True,
        read_only=True,
    )
    est_active = serializers.BooleanField(read_only=True)
    est_validee = serializers.BooleanField(read_only=True)
    autorise_immersion = serializers.BooleanField(read_only=True)
    necessite_reorganisation = serializers.BooleanField(read_only=True)
    necessite_retrait_organisation = serializers.BooleanField(
        read_only=True
    )
    consequences_appliquees = serializers.BooleanField(read_only=True)

    class Meta:
        model = VisiteMedicale
        fields = [
            "id",
            "affectation_centre",
            "session_id",
            "centre_id",
            "numero_visite",
            "est_courante",
            "date_visite",
            "resultat",
            "statut",
            "observations_medicales",
            "consignes_operationnelles",
            "document_medical",
            "date_prochaine_visite",
            "agent_sante",
            "date_validation",
            "statut_application",
            "date_application",
            "erreur_application",
            "est_active",
            "est_validee",
            "autorise_immersion",
            "necessite_reorganisation",
            "necessite_retrait_organisation",
            "consequences_appliquees",
            "restrictions",
            "created_at",
            "updated_at",
            "deleted_at",
        ]


class RestrictionMedicaleInputSerializer(serializers.Serializer):
    libelle = serializers.CharField(max_length=180)
    type_restriction = serializers.ChoiceField(
        choices=RestrictionMedicale.TypeRestriction.choices,
        default=RestrictionMedicale.TypeRestriction.ADAPTATION,
    )
    modules_concernes = serializers.ListField(
        child=serializers.ChoiceField(
            choices=RestrictionMedicale.ModuleConcerne.choices,
        ),
        allow_empty=False,
    )
    description_medicale = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    consigne_operationnelle = serializers.CharField(
        allow_blank=False,
    )
    niveau_sensibilite = serializers.ChoiceField(
        choices=RestrictionMedicale.NiveauSensibilite.choices,
        default=RestrictionMedicale.NiveauSensibilite.CONFIDENTIEL,
    )
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(
        required=False,
        allow_null=True,
    )

    def validate_modules_concernes(self, value):
        return list(dict.fromkeys(value))

    def validate(self, attrs):
        date_debut = attrs.get("date_debut")
        date_fin = attrs.get("date_fin")
        if date_debut and date_fin and date_fin < date_debut:
            raise serializers.ValidationError(
                {
                    "date_fin": (
                        "La date de fin ne peut pas précéder "
                        "la date de début."
                    )
                }
            )
        return attrs


class RestrictionMedicaleCreateSerializer(
    RestrictionMedicaleInputSerializer
):
    visite_medicale_id = serializers.IntegerField(min_value=1)


class RestrictionMedicaleUpdateSerializer(
    RestrictionMedicaleInputSerializer
):
    libelle = serializers.CharField(
        max_length=180,
        required=False,
    )
    type_restriction = serializers.ChoiceField(
        choices=RestrictionMedicale.TypeRestriction.choices,
        required=False,
    )
    modules_concernes = serializers.ListField(
        child=serializers.ChoiceField(
            choices=RestrictionMedicale.ModuleConcerne.choices,
        ),
        allow_empty=False,
        required=False,
    )
    consigne_operationnelle = serializers.CharField(
        allow_blank=False,
        required=False,
    )
    niveau_sensibilite = serializers.ChoiceField(
        choices=RestrictionMedicale.NiveauSensibilite.choices,
        required=False,
    )


class EnregistrementVisiteMedicaleInputSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    resultat = serializers.ChoiceField(
        choices=VisiteMedicale.Resultat.choices,
    )
    date_visite = serializers.DateTimeField(required=False)
    observations_medicales = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    consignes_operationnelles = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    document_medical = serializers.FileField(
        required=False,
        allow_null=True,
    )
    date_prochaine_visite = serializers.DateField(
        required=False,
        allow_null=True,
    )
    restrictions = RestrictionMedicaleInputSerializer(
        many=True,
        required=False,
        default=list,
    )

    def validate(self, attrs):
        resultat = attrs["resultat"]
        restrictions = attrs.get("restrictions", [])

        if (
            resultat
            in {
                VisiteMedicale.Resultat.APTE_SOUS_RESERVE,
                VisiteMedicale.Resultat.DISPENSE,
            }
            and not restrictions
        ):
            raise serializers.ValidationError(
                {
                    "restrictions": (
                        "Ce résultat exige au moins une restriction "
                        "opérationnelle."
                    )
                }
            )

        if (
            resultat != VisiteMedicale.Resultat.INAPTE_TEMPORAIRE
            and attrs.get("date_prochaine_visite")
        ):
            raise serializers.ValidationError(
                {
                    "date_prochaine_visite": (
                        "Une contre-visite ne peut être programmée "
                        "que pour une inaptitude temporaire."
                    )
                }
            )

        return attrs


class BrouillonVisiteMedicaleInputSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    resultat = serializers.ChoiceField(
        choices=VisiteMedicale.Resultat.choices,
        required=False,
        allow_blank=True,
    )
    date_visite = serializers.DateTimeField(required=False)
    observations_medicales = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    consignes_operationnelles = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    document_medical = serializers.FileField(
        required=False,
        allow_null=True,
    )
    date_prochaine_visite = serializers.DateField(
        required=False,
        allow_null=True,
    )
    restrictions = RestrictionMedicaleInputSerializer(
        many=True,
        required=False,
    )


class ContreVisiteMedicaleInputSerializer(
    EnregistrementVisiteMedicaleInputSerializer
):
    pass


class LeverRestrictionInputSerializer(serializers.Serializer):
    motif = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class FiltreVisiteMedicaleSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    affectation_centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    immerge_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    resultat = serializers.ChoiceField(
        choices=VisiteMedicale.Resultat.choices,
        required=False,
    )
    statut = serializers.ChoiceField(
        choices=VisiteMedicale.Statut.choices,
        required=False,
    )
    statut_application = serializers.ChoiceField(
        choices=VisiteMedicale.StatutApplication.choices,
        required=False,
    )
    est_courante = serializers.BooleanField(required=False)
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
    )

    def validate(self, attrs):
        if not any(
            attrs.get(champ)
            for champ in (
                "session_id",
                "centre_id",
                "affectation_centre_id",
                "immerge_id",
            )
        ):
            raise serializers.ValidationError(
                "Au moins un périmètre ou un immergé est requis."
            )
        return attrs


class FiltreRestrictionMedicaleSerializer(serializers.Serializer):
    visite_medicale_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    affectation_centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    module = serializers.ChoiceField(
        choices=RestrictionMedicale.ModuleConcerne.choices,
        required=False,
    )
    type_restriction = serializers.ChoiceField(
        choices=RestrictionMedicale.TypeRestriction.choices,
        required=False,
    )
    statut = serializers.ChoiceField(
        choices=RestrictionMedicale.Statut.choices,
        required=False,
    )
    date_reference = serializers.DateField(required=False)
    seulement_applicables = serializers.BooleanField(
        required=False,
        default=False,
    )
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
    )

    def validate(self, attrs):
        if not any(
            attrs.get(champ)
            for champ in (
                "visite_medicale_id",
                "session_id",
                "centre_id",
                "affectation_centre_id",
            )
        ):
            raise serializers.ValidationError(
                "Un périmètre médical est requis."
            )
        return attrs


class CandidatsVisiteMedicaleQuerySerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    avec_visite_courante = serializers.BooleanField(required=False)
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
    )


class ProchaineVisiteQuerySerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    apres_affectation_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )


class StatistiquesVisitesQuerySerializer(serializers.Serializer):
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )

    def validate(self, attrs):
        if not attrs.get("session_id") and not attrs.get("centre_id"):
            raise serializers.ValidationError(
                "La session ou le centre est obligatoire."
            )
        return attrs


class StatistiqueVisiteMedicaleSerializer(serializers.Serializer):
    resultat = serializers.ChoiceField(
        choices=VisiteMedicale.Resultat.choices,
    )
    total = serializers.IntegerField(min_value=0)


class ImpactMedicalQuerySerializer(serializers.Serializer):
    module = serializers.ChoiceField(
        choices=RestrictionMedicale.ModuleConcerne.choices,
        required=False,
    )
    date_reference = serializers.DateField(required=False)


class DecisionMedicaleSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField()
    module = serializers.CharField()
    etat = serializers.CharField()
    resultat = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    autorise = serializers.BooleanField()
    dispense = serializers.BooleanField()
    necessite_adaptation = serializers.BooleanField()
    consignes = serializers.ListField(
        child=serializers.DictField(),
    )


class ResultatApplicationMedicaleSerializer(serializers.Serializer):
    visite_medicale_id = serializers.IntegerField()
    affectation_centre_id = serializers.IntegerField()
    resultat = serializers.CharField()
    statut_application = serializers.CharField()
    organisation = serializers.DictField()
    modules_concernes = serializers.ListField(
        child=serializers.CharField(),
    )
    decisions_modules = serializers.DictField()


class ResultatEnregistrementVisiteSerializer(serializers.Serializer):
    visite_medicale_id = serializers.IntegerField()
    affectation_centre_id = serializers.IntegerField()
    numero_visite = serializers.IntegerField()
    resultat = serializers.CharField()
    statut = serializers.CharField()
    application = ResultatApplicationMedicaleSerializer()
    prochaine_affectation_centre_id = serializers.IntegerField(
        required=False,
        allow_null=True,
    )
