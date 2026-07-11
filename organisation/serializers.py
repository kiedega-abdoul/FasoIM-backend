from __future__ import annotations

from rest_framework import serializers

from .models import (
    AffectationGroupe,
    AttributionLit,
    Dortoir,
    Groupe,
    Lit,
    RegleOrganisationCentre,
    Section,
)


class ObjetLieResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField(required=False, allow_blank=True)
    nom = serializers.CharField(required=False, allow_blank=True)


class ActeurResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    nom_complet = serializers.CharField(required=False, allow_blank=True)


class RegleOrganisationCentreSerializer(serializers.ModelSerializer):
    session = ObjetLieResumeSerializer(read_only=True)
    centre = ObjetLieResumeSerializer(read_only=True)
    validee_par = ActeurResumeSerializer(read_only=True)
    hebergement_active = serializers.BooleanField(read_only=True)
    visite_medicale_active = serializers.BooleanField(read_only=True)
    est_validee = serializers.BooleanField(read_only=True)

    class Meta:
        model = RegleOrganisationCentre
        fields = [
            "id",
            "session",
            "centre",
            "seuil_division_sections",
            "capacite_max_section",
            "seuil_division_groupes",
            "capacite_max_groupe",
            "repartition_sections_groupes_automatique",
            "attribution_lits_automatique",
            "lieu_accueil",
            "heure_accueil",
            "horaires_generaux",
            "consignes_accueil",
            "consignes_hebergement",
            "consignes_kits_a_apporter",
            "consignes_repas",
            "regles_discipline",
            "consignes_internes",
            "directives_locales",
            "statut",
            "validee_par",
            "date_validation",
            "date_pret_publication",
            "hebergement_active",
            "visite_medicale_active",
            "est_validee",
            "created_at",
            "updated_at",
        ]


class RegleOrganisationCentreInputSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    seuil_division_sections = serializers.IntegerField(min_value=2)
    capacite_max_section = serializers.IntegerField(min_value=1)
    seuil_division_groupes = serializers.IntegerField(min_value=2)
    capacite_max_groupe = serializers.IntegerField(min_value=1)
    repartition_sections_groupes_automatique = serializers.BooleanField(
        default=True
    )
    attribution_lits_automatique = serializers.BooleanField(default=True)
    lieu_accueil = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
    )
    heure_accueil = serializers.TimeField(required=False, allow_null=True)
    horaires_generaux = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    consignes_accueil = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    consignes_hebergement = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    consignes_kits_a_apporter = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    consignes_repas = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    regles_discipline = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    consignes_internes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    directives_locales = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if attrs["capacite_max_groupe"] > attrs["capacite_max_section"]:
            raise serializers.ValidationError(
                {
                    "capacite_max_groupe": (
                        "La capacité maximale d'un groupe ne peut pas "
                        "dépasser celle d'une section."
                    )
                }
            )
        return attrs


class RegleOrganisationCentreUpdateSerializer(serializers.Serializer):
    seuil_division_sections = serializers.IntegerField(
        min_value=2,
        required=False,
    )
    capacite_max_section = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    seuil_division_groupes = serializers.IntegerField(
        min_value=2,
        required=False,
    )
    capacite_max_groupe = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    repartition_sections_groupes_automatique = serializers.BooleanField(
        required=False
    )
    attribution_lits_automatique = serializers.BooleanField(required=False)
    lieu_accueil = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
    )
    heure_accueil = serializers.TimeField(required=False, allow_null=True)
    horaires_generaux = serializers.CharField(required=False, allow_blank=True)
    consignes_accueil = serializers.CharField(required=False, allow_blank=True)
    consignes_hebergement = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    consignes_kits_a_apporter = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    consignes_repas = serializers.CharField(required=False, allow_blank=True)
    regles_discipline = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    consignes_internes = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    directives_locales = serializers.CharField(
        required=False,
        allow_blank=True,
    )


class SectionSerializer(serializers.ModelSerializer):
    session = ObjetLieResumeSerializer(read_only=True)
    centre = ObjetLieResumeSerializer(read_only=True)

    class Meta:
        model = Section
        fields = [
            "id",
            "session",
            "centre",
            "nom",
            "code",
            "capacite_max",
            "statut",
            "created_at",
            "updated_at",
        ]


class SectionInputSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    nom = serializers.CharField(max_length=150)
    code = serializers.CharField(max_length=50)
    capacite_max = serializers.IntegerField(min_value=1)
    statut = serializers.ChoiceField(
        choices=Section.Statut.choices,
        required=False,
        default=Section.Statut.ACTIVE,
    )


class SectionUpdateSerializer(serializers.Serializer):
    nom = serializers.CharField(max_length=150, required=False)
    code = serializers.CharField(max_length=50, required=False)
    capacite_max = serializers.IntegerField(min_value=1, required=False)
    statut = serializers.ChoiceField(
        choices=Section.Statut.choices,
        required=False,
    )


class GroupeSerializer(serializers.ModelSerializer):
    section = SectionSerializer(read_only=True)

    class Meta:
        model = Groupe
        fields = [
            "id",
            "section",
            "nom",
            "code",
            "capacite_max",
            "statut",
            "created_at",
            "updated_at",
        ]


class GroupeInputSerializer(serializers.Serializer):
    section_id = serializers.IntegerField(min_value=1)
    nom = serializers.CharField(max_length=150)
    code = serializers.CharField(max_length=50)
    capacite_max = serializers.IntegerField(min_value=1)
    statut = serializers.ChoiceField(
        choices=Groupe.Statut.choices,
        required=False,
        default=Groupe.Statut.ACTIF,
    )


class GroupeUpdateSerializer(serializers.Serializer):
    nom = serializers.CharField(max_length=150, required=False)
    code = serializers.CharField(max_length=50, required=False)
    capacite_max = serializers.IntegerField(min_value=1, required=False)
    statut = serializers.ChoiceField(
        choices=Groupe.Statut.choices,
        required=False,
    )


class AffectationCentreResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    immerge_id = serializers.IntegerField()
    session_id = serializers.IntegerField()
    centre_id = serializers.IntegerField()
    code_fasoim = serializers.SerializerMethodField()

    def get_code_fasoim(self, obj):
        immerge = getattr(obj, "immerge", None)
        return (
            getattr(immerge, "code_fasoim", None)
            or getattr(immerge, "matricule_fasoim", None)
        )


class AffectationGroupeSerializer(serializers.ModelSerializer):
    affectation_centre = AffectationCentreResumeSerializer(read_only=True)
    groupe = GroupeSerializer(read_only=True)
    affecte_par = ActeurResumeSerializer(read_only=True)

    class Meta:
        model = AffectationGroupe
        fields = [
            "id",
            "affectation_centre",
            "groupe",
            "statut",
            "affecte_par",
            "date_affectation",
            "observations",
            "created_at",
            "updated_at",
        ]


class AffectationGroupeManuelleInputSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    groupe_id = serializers.IntegerField(min_value=1)
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class DortoirSerializer(serializers.ModelSerializer):
    centre = ObjetLieResumeSerializer(read_only=True)

    class Meta:
        model = Dortoir
        fields = [
            "id",
            "centre",
            "nom",
            "capacite",
            "sexe_dortoir",
            "statut",
            "created_at",
            "updated_at",
        ]


class DortoirInputSerializer(serializers.Serializer):
    centre_id = serializers.IntegerField(min_value=1)
    nom = serializers.CharField(max_length=150)
    capacite = serializers.IntegerField(min_value=1)
    sexe_dortoir = serializers.ChoiceField(
        choices=Dortoir.SexeDortoir.choices,
    )
    statut = serializers.ChoiceField(
        choices=Dortoir.Statut.choices,
        required=False,
        default=Dortoir.Statut.ACTIF,
    )


class DortoirUpdateSerializer(serializers.Serializer):
    nom = serializers.CharField(max_length=150, required=False)
    capacite = serializers.IntegerField(min_value=1, required=False)
    sexe_dortoir = serializers.ChoiceField(
        choices=Dortoir.SexeDortoir.choices,
        required=False,
    )


class LitSerializer(serializers.ModelSerializer):
    dortoir = DortoirSerializer(read_only=True)
    est_utilisable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Lit
        fields = [
            "id",
            "dortoir",
            "numero_lit",
            "statut",
            "est_utilisable",
            "created_at",
            "updated_at",
        ]


class LitInputSerializer(serializers.Serializer):
    dortoir_id = serializers.IntegerField(min_value=1)
    numero_lit = serializers.CharField(max_length=50)
    statut = serializers.ChoiceField(
        choices=Lit.Statut.choices,
        required=False,
        default=Lit.Statut.DISPONIBLE,
    )


class LitUpdateSerializer(serializers.Serializer):
    numero_lit = serializers.CharField(max_length=50, required=False)


class AttributionLitSerializer(serializers.ModelSerializer):
    affectation_centre = AffectationCentreResumeSerializer(read_only=True)
    lit = LitSerializer(read_only=True)
    attribue_par = ActeurResumeSerializer(read_only=True)

    class Meta:
        model = AttributionLit
        fields = [
            "id",
            "affectation_centre",
            "lit",
            "statut",
            "date_attribution",
            "date_liberation",
            "attribue_par",
            "observations",
            "created_at",
            "updated_at",
        ]


class AttributionLitManuelleInputSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    lit_id = serializers.IntegerField(min_value=1)
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class GenererStructuresInputSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    recreer = serializers.BooleanField(required=False, default=False)


class PropositionOrganisationLotInputSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    nombre = serializers.IntegerField(min_value=1, max_value=5000)


class ActionOrganisationLotInputSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=5000,
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_ids(self, value):
        return list(dict.fromkeys(value))


class RejetOrganisationLotInputSerializer(ActionOrganisationLotInputSerializer):
    observations = serializers.CharField(
        required=True,
        allow_blank=False,
    )


class LiberationLitInputSerializer(serializers.Serializer):
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class FiltreOrganisationSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1, required=False)
    centre_id = serializers.IntegerField(min_value=1, required=False)
    region_id = serializers.IntegerField(min_value=1, required=False)
    statut = serializers.CharField(required=False, allow_blank=False)
    recherche = serializers.CharField(required=False, allow_blank=False)

    def validate(self, attrs):
        if not any(
            attrs.get(champ)
            for champ in ("session_id", "centre_id", "region_id")
        ):
            raise serializers.ValidationError(
                "Au moins un périmètre session, région ou centre est requis."
            )
        return attrs


class FiltreGroupeSerializer(FiltreOrganisationSerializer):
    section_id = serializers.IntegerField(min_value=1, required=False)


class FiltreAffectationGroupeSerializer(FiltreGroupeSerializer):
    groupe_id = serializers.IntegerField(min_value=1, required=False)
    affectation_centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )


class FiltreHebergementSerializer(serializers.Serializer):
    centre_id = serializers.IntegerField(min_value=1, required=True)
    region_id = serializers.IntegerField(min_value=1, required=False)
    dortoir_id = serializers.IntegerField(min_value=1, required=False)
    sexe_dortoir = serializers.ChoiceField(
        choices=Dortoir.SexeDortoir.choices,
        required=False,
    )
    statut = serializers.CharField(required=False, allow_blank=False)
    recherche = serializers.CharField(required=False, allow_blank=False)


class FiltreAttributionLitSerializer(FiltreHebergementSerializer):
    session_id = serializers.IntegerField(min_value=1, required=True)
    lit_id = serializers.IntegerField(min_value=1, required=False)
    affectation_centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )


class TacheOrganisationLanceeSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    operation = serializers.CharField()
    message = serializers.CharField()


class ProgressionOrganisationSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    operation = serializers.CharField(required=False, allow_blank=True)
    statut = serializers.CharField()
    progression = serializers.IntegerField(min_value=0, max_value=100)
    message = serializers.CharField(required=False, allow_blank=True)
    total = serializers.IntegerField(min_value=0)
    traites = serializers.IntegerField(min_value=0)
    crees = serializers.IntegerField(min_value=0)
    restants = serializers.IntegerField(min_value=0)
    erreurs = serializers.IntegerField(min_value=0)
    resultat = serializers.JSONField(required=False, allow_null=True)
