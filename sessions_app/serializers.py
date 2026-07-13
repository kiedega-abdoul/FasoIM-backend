from rest_framework import serializers

from .models import ParametreSession, SessionImmersion
from .service import ParametreSessionService, SessionImmersionService


class ParametreSessionInputSerializer(serializers.Serializer):
    """Données de paramètres acceptées lors de la création d'une session."""

    mode_entree = serializers.ChoiceField(
        choices=ParametreSession.ModeEntree.choices,
        required=False,
        default=ParametreSession.ModeEntree.IMPORT,
    )
    hebergement_active = serializers.BooleanField(required=False, default=True)
    repas_active = serializers.BooleanField(required=False, default=True)
    visite_medicale_active = serializers.BooleanField(required=False, default=False)
    mode_visite_medicale = serializers.ChoiceField(
        choices=ParametreSession.ModeVisiteMedicale.choices,
        required=False,
        default=ParametreSession.ModeVisiteMedicale.ARRIVEE,
    )
    activites_active = serializers.BooleanField(required=False, default=True)
    evaluation_active = serializers.BooleanField(required=False, default=False)
    attestation_active = serializers.BooleanField(required=False, default=True)
    consultation_publique_active = serializers.BooleanField(required=False, default=True)
    taux_presence_minimum_attestation = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        default="80.00",
        min_value=0,
        max_value=100,
    )
    moyenne_minimum_attestation = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        default="10.00",
        min_value=0,
        max_value=20,
    )
    directives_generales = serializers.CharField(required=False, allow_blank=True)
    consignes_generales = serializers.CharField(required=False, allow_blank=True)
    documents_exiges = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        default=list,
    )

    def validate_documents_exiges(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(
                "La liste des documents exigés doit être un tableau."
            )
        return value


class ParametreSessionSerializer(serializers.ModelSerializer):
    utilise_import = serializers.BooleanField(read_only=True)
    utilise_inscription_volontaire = serializers.BooleanField(read_only=True)

    class Meta:
        model = ParametreSession
        fields = [
            "id",
            "session",
            "mode_entree",
            "hebergement_active",
            "repas_active",
            "visite_medicale_active",
            "mode_visite_medicale",
            "activites_active",
            "evaluation_active",
            "attestation_active",
            "consultation_publique_active",
            "taux_presence_minimum_attestation",
            "moyenne_minimum_attestation",
            "directives_generales",
            "consignes_generales",
            "documents_exiges",
            "utilise_import",
            "utilise_inscription_volontaire",        
        ]
        read_only_fields = [
            "id",
            "session",
            "utilise_import",
            "utilise_inscription_volontaire",
        ]

    def validate_documents_exiges(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(
                "La liste des documents exigés doit être un tableau."
            )
        return value

    def update(self, instance, validated_data):
        return ParametreSessionService.modifier_parametres(instance, validated_data)


class SessionImmersionSerializer(serializers.ModelSerializer):
    parametres = ParametreSessionSerializer(read_only=True)
    est_active = serializers.BooleanField(read_only=True)
    est_modifiable = serializers.BooleanField(read_only=True)
    accepte_import = serializers.BooleanField(read_only=True)
    accepte_inscription_volontaire = serializers.BooleanField(read_only=True)

    class Meta:
        model = SessionImmersion
        fields = [
            "id",
            "nom",
            "code",
            "annee",
            "numero_promotion",
            "type_session",
            "public_cible",
            "date_debut",
            "date_fin",
            "date_ouverture_inscription",
            "date_fermeture_inscription",
            "statut",
            "description",
            "parametres",
            "est_active",
            "est_modifiable",
            "accepte_import",
            "accepte_inscription_volontaire",
        ]
        read_only_fields = [
            "id",
            "code",
            "est_active",
            "est_modifiable",
            "accepte_import",
            "accepte_inscription_volontaire",
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)

        date_debut = attrs.get("date_debut", getattr(self.instance, "date_debut", None))
        date_fin = attrs.get("date_fin", getattr(self.instance, "date_fin", None))

        if date_debut and date_fin and date_fin < date_debut:
            raise serializers.ValidationError({
                "date_fin": "La date de fin ne peut pas être antérieure à la date de début."
            })

        ouverture = attrs.get(
            "date_ouverture_inscription",
            getattr(self.instance, "date_ouverture_inscription", None),
        )
        fermeture = attrs.get(
            "date_fermeture_inscription",
            getattr(self.instance, "date_fermeture_inscription", None),
        )

        if ouverture and fermeture and fermeture < ouverture:
            raise serializers.ValidationError({
                "date_fermeture_inscription": (
                    "La date de fermeture ne peut pas être antérieure à la date d'ouverture."
                )
            })

        type_session = attrs.get("type_session", getattr(self.instance, "type_session", None))
        public_cible = attrs.get("public_cible", getattr(self.instance, "public_cible", None))
        self._validate_coherence_type_public(type_session, public_cible)

        return attrs

    def update(self, instance, validated_data):
        return SessionImmersionService.modifier_session(instance, validated_data)

    @staticmethod
    def _validate_coherence_type_public(type_session, public_cible):
        if not type_session or not public_cible:
            return

        if type_session == SessionImmersion.TypeSession.MIXTE:
            return

        correspondances = {
            SessionImmersion.TypeSession.EXAMEN: [
                SessionImmersion.PublicCible.BEPC,
                SessionImmersion.PublicCible.BAC,
                SessionImmersion.PublicCible.MIXTE,
            ],
            SessionImmersion.TypeSession.CONCOURS: [
                SessionImmersion.PublicCible.CONCOURS,
                SessionImmersion.PublicCible.MIXTE,
            ],
            SessionImmersion.TypeSession.SELECTIONNE: [
                SessionImmersion.PublicCible.SELECTIONNE,
                SessionImmersion.PublicCible.MIXTE,
            ],
            SessionImmersion.TypeSession.VOLONTAIRE: [
                SessionImmersion.PublicCible.VOLONTAIRE,
                SessionImmersion.PublicCible.MIXTE,
            ],
        }

        publics_autorises = correspondances.get(type_session, [])
        if public_cible not in publics_autorises:
            raise serializers.ValidationError({
                "public_cible": "Le public cible n'est pas cohérent avec le type de session."
            })


class SessionImmersionCreateSerializer(SessionImmersionSerializer):
    parametres = ParametreSessionInputSerializer(required=False)

    class Meta(SessionImmersionSerializer.Meta):
        read_only_fields = SessionImmersionSerializer.Meta.read_only_fields + [
            "statut",
        ]

    def create(self, validated_data):
        parametres_data = validated_data.pop("parametres", {})
        return SessionImmersionService.creer_session_avec_parametres(
            session_data=validated_data,
            parametres_data=parametres_data,
        )
