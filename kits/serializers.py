from __future__ import annotations

from rest_framework import serializers

from .models import ArticleKit, RemiseKit


class SessionKitResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    nom = serializers.CharField()


class CentreKitResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    nom = serializers.CharField()


class ImmergeKitResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code_fasoim = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    type_immerge = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )


class AffectationCentreKitResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    session = SessionKitResumeSerializer()
    centre = CentreKitResumeSerializer()
    immerge = ImmergeKitResumeSerializer()
    statut = serializers.CharField()


class ActeurKitResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
    )
    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )


class ArticleKitSerializer(serializers.ModelSerializer):
    session = SessionKitResumeSerializer(read_only=True)
    centre = CentreKitResumeSerializer(
        read_only=True,
        allow_null=True,
    )
    type_kit_libelle = serializers.CharField(
        source="get_type_kit_display",
        read_only=True,
    )
    statut_libelle = serializers.CharField(
        source="get_statut_display",
        read_only=True,
    )
    portee = serializers.SerializerMethodField()

    class Meta:
        model = ArticleKit
        fields = [
            "id",
            "session",
            "centre",
            "designation",
            "description",
            "type_kit",
            "type_kit_libelle",
            "quantite",
            "unite",
            "obligatoire",
            "ordre",
            "statut",
            "statut_libelle",
            "portee",
        ]

    def get_portee(self, obj):
        if obj.centre_id:
            return {
                "type": "CENTRE",
                "centre_id": obj.centre_id,
                "centre_nom": obj.centre.nom,
            }
        return {
            "type": "SESSION",
            "centre_id": None,
            "centre_nom": None,
        }


class ArticleKitCreateSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    designation = serializers.CharField(max_length=180)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    type_kit = serializers.ChoiceField(
        choices=ArticleKit.TypeKit.choices,
    )
    quantite = serializers.IntegerField(
        min_value=1,
        default=1,
    )
    unite = serializers.CharField(
        max_length=50,
        default="unité",
    )
    obligatoire = serializers.BooleanField(default=True)
    ordre = serializers.IntegerField(
        min_value=0,
        default=0,
    )
    statut = serializers.ChoiceField(
        choices=ArticleKit.Statut.choices,
        default=ArticleKit.Statut.ACTIF,
    )

    def validate(self, attrs):
        if (
            attrs["type_kit"] == ArticleKit.TypeKit.A_APPORTER
            and not attrs.get("centre_id")
        ):
            raise serializers.ValidationError(
                {
                    "centre_id": (
                        "Un article à apporter doit être rattaché "
                        "à un centre."
                    )
                }
            )
        return attrs


class ArticleKitUpdateSerializer(serializers.Serializer):
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    designation = serializers.CharField(
        max_length=180,
        required=False,
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    type_kit = serializers.ChoiceField(
        choices=ArticleKit.TypeKit.choices,
        required=False,
    )
    quantite = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    unite = serializers.CharField(
        max_length=50,
        required=False,
    )
    obligatoire = serializers.BooleanField(required=False)
    ordre = serializers.IntegerField(
        min_value=0,
        required=False,
    )
    statut = serializers.ChoiceField(
        choices=ArticleKit.Statut.choices,
        required=False,
    )


class FiltreArticleKitSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    type_kit = serializers.ChoiceField(
        choices=ArticleKit.TypeKit.choices,
        required=False,
    )
    statut = serializers.ChoiceField(
        choices=ArticleKit.Statut.choices,
        required=False,
    )
    obligatoire = serializers.BooleanField(required=False)
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
    )
    inclure_globaux = serializers.BooleanField(
        required=False,
        default=True,
    )

    def validate(self, attrs):
        if not attrs.get("session_id") and not attrs.get("centre_id"):
            raise serializers.ValidationError(
                "La session ou le centre est obligatoire."
            )
        return attrs


class ArticlesApplicablesQuerySerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)


class RemiseKitSerializer(serializers.ModelSerializer):
    affectation_centre = (
        AffectationCentreKitResumeSerializer(read_only=True)
    )
    article_kit = ArticleKitSerializer(read_only=True)
    remis_par = ActeurKitResumeSerializer(
        read_only=True,
        allow_null=True,
    )
    statut_remise_libelle = serializers.CharField(
        source="get_statut_remise_display",
        read_only=True,
    )
    est_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = RemiseKit
        fields = [
            "id",
            "affectation_centre",
            "article_kit",
            "quantite_prevue",
            "quantite_remise",
            "statut_remise",
            "statut_remise_libelle",
            "observations",
            "remis_par",
            "date_remise",
            "est_complete",
        ]


class FiltreRemiseKitSerializer(serializers.Serializer):
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
    article_kit_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    statut_remise = serializers.ChoiceField(
        choices=RemiseKit.StatutRemise.choices,
        required=False,
    )
    remis_par_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(required=False)
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
                "article_kit_id",
            )
        ):
            raise serializers.ValidationError(
                "Un périmètre de remise est obligatoire."
            )

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


class PreparerRemiseIndividuelleSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    article_kit_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
    )

    def validate_article_kit_ids(self, value):
        return list(dict.fromkeys(value))


class EnregistrerRemiseArticleSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    article_kit_id = serializers.IntegerField(min_value=1)
    quantite_remise = serializers.IntegerField(min_value=0)
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class ValiderRemiseCompleteSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    article_kit_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
    )

    def validate_article_kit_ids(self, value):
        return list(dict.fromkeys(value))


class MarquerRemplaceSerializer(serializers.Serializer):
    quantite_remise = serializers.IntegerField(min_value=1)
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class MarquerDispenseSerializer(serializers.Serializer):
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class StatutGlobalRemiseQuerySerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)


class StatutGlobalRemiseSerializer(serializers.Serializer):
    statut = serializers.ChoiceField(
        choices=[
            ("NON_COMMENCEE", "Non commencée"),
            ("PARTIELLE", "Partielle"),
            ("COMPLETE", "Complète"),
            ("AUCUN_ARTICLE", "Aucun article"),
        ]
    )
    articles_attendus = serializers.IntegerField(min_value=0)
    articles_completes = serializers.IntegerField(min_value=0)
    articles_non_commences = serializers.IntegerField(min_value=0)


class OperationMasseKitsSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    affectation_centre_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )
    article_kit_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
    )

    def validate_affectation_centre_ids(self, value):
        valeur = list(dict.fromkeys(value))
        return valeur or None

    def validate_article_kit_ids(self, value):
        return list(dict.fromkeys(value))


class AnnulationMasseKitsSerializer(
    OperationMasseKitsSerializer
):
    affectation_centre_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )


class TacheKitsLanceeSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    operation = serializers.CharField()
    statut = serializers.CharField()
    message = serializers.CharField()


class ProgressionTacheKitsSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    operation = serializers.CharField(
        allow_blank=True,
        required=False,
    )
    statut = serializers.CharField()
    progression = serializers.IntegerField(
        min_value=0,
        max_value=100,
    )
    message = serializers.CharField(
        allow_blank=True,
        required=False,
    )
    total_immerges = serializers.IntegerField(min_value=0)
    immerges_traites = serializers.IntegerField(min_value=0)
    remises_creees = serializers.IntegerField(min_value=0)
    remises_validees = serializers.IntegerField(min_value=0)
    remises_annulees = serializers.IntegerField(min_value=0)
    bloques_medicaux = serializers.IntegerField(min_value=0)
    sans_article = serializers.IntegerField(min_value=0)
    erreurs = serializers.IntegerField(min_value=0)
    resultat = serializers.JSONField(
        required=False,
        allow_null=True,
    )


class StatistiquesKitsQuerySerializer(serializers.Serializer):
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


class StatistiqueRemiseKitSerializer(serializers.Serializer):
    statut_remise = serializers.ChoiceField(
        choices=RemiseKit.StatutRemise.choices,
    )
    total = serializers.IntegerField(min_value=0)
