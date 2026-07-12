from __future__ import annotations

from rest_framework import serializers

from accounts.service import ControleAccesService

from .models import AlerteIncident


class ActeurIncidentResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nom = serializers.SerializerMethodField()

    def get_nom(self, obj):
        return getattr(obj, "nom_complet", "") or getattr(obj, "username", "")


class AlerteIncidentSerializer(serializers.ModelSerializer):
    type_libelle = serializers.CharField(source="get_type_display", read_only=True)
    origine_libelle = serializers.CharField(source="get_origine_display", read_only=True)
    type_concerne_libelle = serializers.CharField(source="get_type_concerne_display", read_only=True)
    categorie_libelle = serializers.CharField(source="get_categorie_display", read_only=True)
    niveau_gravite_libelle = serializers.CharField(source="get_niveau_gravite_display", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    cree_par_resume = ActeurIncidentResumeSerializer(source="cree_par", read_only=True, allow_null=True)
    traite_par_resume = ActeurIncidentResumeSerializer(source="traite_par", read_only=True, allow_null=True)
    concerne = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    contexte = serializers.SerializerMethodField()

    class Meta:
        model = AlerteIncident
        fields = [
            "id",
            "session",
            "centre",
            "affectation_centre",
            "acteur_concerne",
            "type",
            "type_libelle",
            "origine",
            "origine_libelle",
            "type_concerne",
            "type_concerne_libelle",
            "concerne",
            "categorie",
            "categorie_libelle",
            "titre",
            "description",
            "niveau_gravite",
            "niveau_gravite_libelle",
            "statut",
            "statut_libelle",
            "code_detection",
            "module_source",
            "modele_source",
            "objet_source_id",
            "contexte",
            "est_bloquante",
            "resolution_automatique",
            "cree_par_resume",
            "traite_par_resume",
            "nombre_occurrences",
            "niveau_escalade",
            "date_premiere_detection",
            "date_derniere_detection",
            "date_derniere_escalade",
            "date_signalement",
            "date_prise_en_charge",
            "date_resolution",
            "date_cloture",
            "resolution",
            "observations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _peut_lire_sante(self, obj):
        request = self.context.get("request")
        acteur = getattr(request, "user", None)
        if not acteur or not getattr(acteur, "is_authenticated", False):
            return False
        if getattr(acteur, "is_superuser", False) or obj.cree_par_id == getattr(acteur, "id", None):
            return True
        resultat = ControleAccesService.acteur_peut(
            acteur,
            "consulter_visites_medicales",
            session_id=obj.session_id,
            centre_id=obj.centre_id,
        )
        return resultat.autorise


    def _peut_lire_technique(self, obj):
        request = self.context.get("request")
        acteur = getattr(request, "user", None)
        if not acteur or not getattr(acteur, "is_authenticated", False):
            return False
        if getattr(acteur, "is_superuser", False):
            return True
        resultat = ControleAccesService.acteur_peut(
            acteur,
            "generer_alerte_automatique",
            session_id=obj.session_id,
            centre_id=obj.centre_id,
        )
        return resultat.autorise

    def to_representation(self, instance):
        donnees = super().to_representation(instance)
        if not self._peut_lire_technique(instance):
            for champ in (
                "code_detection",
                "module_source",
                "modele_source",
                "objet_source_id",
                "contexte",
            ):
                donnees.pop(champ, None)
        return donnees

    def get_description(self, obj):
        if (
            obj.categorie == AlerteIncident.Categorie.SANTE
            and obj.origine == AlerteIncident.Origine.MANUELLE
            and not self._peut_lire_sante(obj)
        ):
            return "Incident de santé signalé. Détails réservés aux acteurs autorisés."
        return obj.description

    def get_contexte(self, obj):
        request = self.context.get("request")
        acteur = getattr(request, "user", None)
        if self._peut_lire_technique(obj):
            return obj.contexte
        return {}

    def get_concerne(self, obj):
        if obj.type_concerne == AlerteIncident.TypeConcerne.IMMERGE:
            if obj.affectation_centre_id:
                immerge = obj.affectation_centre.immerge
                return {
                    "type": obj.type_concerne,
                    "id": immerge.id,
                    "libelle": str(immerge),
                    "affectation_centre_id": obj.affectation_centre_id,
                }
            return {
                "type": obj.type_concerne,
                "id": obj.objet_source_id,
                "libelle": obj.titre,
            }
        if obj.type_concerne == AlerteIncident.TypeConcerne.ACTEUR and obj.acteur_concerne:
            return {
                "type": obj.type_concerne,
                "id": obj.acteur_concerne_id,
                "libelle": str(obj.acteur_concerne),
            }
        if obj.type_concerne == AlerteIncident.TypeConcerne.CENTRE and obj.centre:
            return {
                "type": obj.type_concerne,
                "id": obj.centre_id,
                "libelle": obj.centre.nom,
            }
        if obj.type_concerne == AlerteIncident.TypeConcerne.SESSION and obj.session:
            return {
                "type": obj.type_concerne,
                "id": obj.session_id,
                "libelle": str(obj.session),
            }
        return {
            "type": obj.type_concerne,
            "id": obj.objet_source_id,
            "libelle": obj.titre,
        }


class SignalementIncidentSerializer(serializers.Serializer):
    """Trois champs visibles : gravité, concerné et raison.

    L'acteur qui signale provient obligatoirement du JWT et ne peut donc pas être
    choisi ou falsifié dans le corps de la requête.
    """

    niveau_gravite = serializers.ChoiceField(choices=AlerteIncident.NiveauGravite.choices)
    concerne = serializers.DictField()
    raison = serializers.CharField(min_length=10, max_length=5000, trim_whitespace=True)

    def to_internal_value(self, data):
        inconnus = set(data.keys()) - set(self.fields.keys()) if hasattr(data, "keys") else set()
        if inconnus:
            raise serializers.ValidationError(
                {champ: "Ce champ n'est pas autorisé dans le signalement rapide." for champ in sorted(inconnus)}
            )
        return super().to_internal_value(data)

    def validate_concerne(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Le concerné doit contenir un type et un identifiant.")
        type_concerne = value.get("type")
        identifiant = value.get("id")
        types_autorises = {
            AlerteIncident.TypeConcerne.IMMERGE,
            AlerteIncident.TypeConcerne.ACTEUR,
            AlerteIncident.TypeConcerne.CENTRE,
            AlerteIncident.TypeConcerne.SESSION,
        }
        if type_concerne not in types_autorises:
            raise serializers.ValidationError(
                "Le type doit être IMMERGE, ACTEUR, CENTRE ou SESSION."
            )
        try:
            identifiant = int(identifiant)
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError("L'identifiant du concerné est invalide.") from exc
        if identifiant <= 0:
            raise serializers.ValidationError("L'identifiant du concerné doit être positif.")
        return {"type": type_concerne, "id": identifiant}


class ModificationSignalementSerializer(serializers.Serializer):
    niveau_gravite = serializers.ChoiceField(
        choices=AlerteIncident.NiveauGravite.choices,
        required=False,
    )
    raison = serializers.CharField(
        min_length=10,
        max_length=5000,
        trim_whitespace=True,
        required=False,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Aucune modification n'a été fournie.")
        return attrs


class ObservationIncidentSerializer(serializers.Serializer):
    observation = serializers.CharField(required=False, allow_blank=True, max_length=3000)


class MotifIncidentSerializer(serializers.Serializer):
    motif = serializers.CharField(min_length=5, max_length=3000, trim_whitespace=True)


class ResolutionIncidentSerializer(serializers.Serializer):
    resolution = serializers.CharField(min_length=10, max_length=5000, trim_whitespace=True)


class FiltreIncidentSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=False, min_value=1)
    centre_id = serializers.IntegerField(required=False, min_value=1)
    categorie = serializers.ChoiceField(choices=AlerteIncident.Categorie.choices, required=False)
    niveau_gravite = serializers.ChoiceField(
        choices=AlerteIncident.NiveauGravite.choices,
        required=False,
    )
    statut = serializers.ChoiceField(choices=AlerteIncident.Statut.choices, required=False)
    origine = serializers.ChoiceField(choices=AlerteIncident.Origine.choices, required=False)
    type_incident = serializers.ChoiceField(choices=AlerteIncident.Type.choices, required=False)
    cree_par_id = serializers.IntegerField(required=False, min_value=1)
    traite_par_id = serializers.IntegerField(required=False, min_value=1)
    est_bloquante = serializers.BooleanField(required=False)
    code_detection = serializers.CharField(required=False, max_length=100)
    recherche = serializers.CharField(required=False, max_length=200)


class StatistiquesIncidentQuerySerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=False, min_value=1)
    centre_id = serializers.IntegerField(required=False, min_value=1)


class LancerScanSerializer(serializers.Serializer):
    module = serializers.ChoiceField(
        choices=[
            "tous",
            "accounts",
            "sessions_app",
            "imports_app",
            "immerges",
            "affectations",
            "organisation",
            "sante",
            "kits",
            "activites",
            "repas",
        ],
        default="tous",
        required=False,
    )


class TacheIncidentLanceeSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    operation = serializers.CharField()
    statut = serializers.CharField()


class ProgressionIncidentSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    operation = serializers.CharField()
    statut = serializers.CharField()
    progression = serializers.IntegerField()
    message = serializers.CharField()
    resultat = serializers.JSONField(allow_null=True)
    erreur = serializers.CharField()
    updated_at = serializers.CharField(required=False)
