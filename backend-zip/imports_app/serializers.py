from rest_framework import serializers

from sessions_app.models import SessionImmersion

from .models import (
    CorrespondanceColonneImport,
    ErreurImport,
    ImportOfficiel,
    LigneImport,
)
from .service import (
    ChampsAttendusImportService,
    CorrespondanceColonneImportService,
    ImportOfficielService,
)


class ChampAttenduImportSerializer(serializers.Serializer):
    """Champ attendu par FasoIM pour un type d'import donné."""

    code = serializers.CharField(read_only=True)
    libelle = serializers.CharField(read_only=True)
    obligatoire = serializers.BooleanField(read_only=True)


class ChampsAttendusTypeSourceSerializer(serializers.Serializer):
    """Réponse utilisée par le frontend pour construire l'écran de correspondance."""

    type_source = serializers.ChoiceField(choices=ImportOfficiel.TypeSource.choices)
    champs = ChampAttenduImportSerializer(many=True, read_only=True)

    @staticmethod
    def construire(type_source):
        return {
            "type_source": type_source,
            "champs": ChampsAttendusImportService.lister(type_source),
        }


class ActeurImportResumeSerializer(serializers.Serializer):
    """Résumé d'un acteur lié à un import."""

    id = serializers.IntegerField(read_only=True)
    nom_complet = serializers.SerializerMethodField()
    email = serializers.EmailField(read_only=True)

    def get_nom_complet(self, obj):
        if not obj:
            return ""
        if hasattr(obj, "get_full_name"):
            nom = obj.get_full_name()
            if nom:
                return nom
        return getattr(obj, "username", "") or getattr(obj, "email", "") or str(obj)


class ImportOfficielListSerializer(serializers.ModelSerializer):
    """Liste compacte des imports officiels.

    On expose seulement les informations utiles à l'écran : état, fichier,
    session, type, statistiques et dates métier. Les champs internes comme
    hash_fichier, created_at, updated_at et deleted_at ne sortent pas.
    """

    session_code = serializers.SerializerMethodField()
    session_libelle = serializers.SerializerMethodField()
    type_source_libelle = serializers.CharField(source="get_type_source_display", read_only=True)
    type_fichier_libelle = serializers.CharField(source="get_type_fichier_display", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    importe_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = ImportOfficiel
        fields = [
            "id",
            "session",
            "session_code",
            "session_libelle",
            "type_source",
            "type_source_libelle",
            "type_fichier",
            "type_fichier_libelle",
            "nom_fichier_original",
            "taille_fichier",
            "statut",
            "statut_libelle",
            "total_lignes",
            "lignes_valides",
            "lignes_erreur",
            "lignes_ignorees",
            "lignes_importees",
            "importe_par_nom",
            "date_import",
            "date_lecture_colonnes",
            "date_correspondance",
            "date_validation",
            "date_confirmation",
            "date_fin_traitement",
        ]
        read_only_fields = fields

    def get_session_code(self, obj):
        return getattr(obj.session, "code", "") if obj.session_id else ""

    def get_session_libelle(self, obj):
        if not obj.session_id:
            return ""
        session = obj.session
        return (
            getattr(session, "libelle", "")
            or getattr(session, "nom", "")
            or getattr(session, "titre", "")
            or getattr(session, "code", "")
            or str(session)
        )

    def get_importe_par_nom(self, obj):
        acteur = getattr(obj, "importe_par", None)
        if not acteur:
            return ""
        if hasattr(acteur, "get_full_name"):
            nom = acteur.get_full_name()
            if nom:
                return nom
        return getattr(acteur, "username", "") or getattr(acteur, "email", "") or str(acteur)


class CorrespondanceColonneImportSerializer(serializers.ModelSerializer):
    """Correspondance confirmée entre une colonne source et un champ FasoIM."""

    class Meta:
        model = CorrespondanceColonneImport
        fields = [
            "id",
            "import_officiel",
            "champ_cible",
            "libelle_champ_cible",
            "colonne_source",
            "obligatoire",
            "confirmee",
            "ordre",
            "transformation",
        ]
        read_only_fields = fields


class ImportOfficielDetailSerializer(ImportOfficielListSerializer):
    """Détail d'un import officiel.

    Les colonnes détectées et les paramètres de lecture sont exposés pour que le
    frontend puisse afficher l'écran de correspondance. Le contenu inutile du
    haut du fichier, les logos et les images ne sont pas stockés ici.
    """

    importe_par = ActeurImportResumeSerializer(read_only=True)
    correspondance_confirmee_par = ActeurImportResumeSerializer(read_only=True)
    confirme_par = ActeurImportResumeSerializer(read_only=True)
    correspondances = CorrespondanceColonneImportSerializer(many=True, read_only=True)
    champs_attendus = serializers.SerializerMethodField()

    class Meta(ImportOfficielListSerializer.Meta):
        fields = ImportOfficielListSerializer.Meta.fields + [
            "colonnes_detectees",
            "parametres_lecture",
            "message_erreur",
            "commentaire",
            "importe_par",
            "correspondance_confirmee_par",
            "confirme_par",
            "correspondances",
            "champs_attendus",
        ]
        read_only_fields = fields

    def get_champs_attendus(self, obj):
        return ChampsAttendusImportService.lister(obj.type_source)


class ImportOfficielCreateSerializer(serializers.ModelSerializer):
    """Création d'un import officiel depuis le frontend.

    Le frontend envoie seulement session, type_source, fichier et commentaire.
    Le backend calcule le nom original, le type de fichier, la taille, le hash,
    l'importateur et lance la lecture asynchrone des colonnes.
    """

    session = serializers.PrimaryKeyRelatedField(
        queryset=SessionImmersion.objects.filter(deleted_at__isnull=True)
    )
    fichier = serializers.FileField(write_only=True)
    commentaire = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    continuer_malgre_doublon = serializers.BooleanField(required=False, default=False, write_only=True)

    class Meta:
        model = ImportOfficiel
        fields = [
            "session",
            "type_source",
            "fichier",
            "commentaire",
            "continuer_malgre_doublon",
        ]

    def validate_fichier(self, fichier):
        nom = getattr(fichier, "name", "") or ""
        from .service import LectureFichierImportService

        LectureFichierImportService.detecter_type_fichier(nom)
        return fichier

    def create(self, validated_data):
        request = self.context.get("request")
        acteur = getattr(request, "user", None) if request else None
        if acteur is not None and not getattr(acteur, "is_authenticated", False):
            acteur = None

        try:
            return ImportOfficielService.creer_import_officiel(
                session=validated_data["session"],
                type_source=validated_data["type_source"],
                fichier=validated_data["fichier"],
                commentaire=validated_data.get("commentaire", ""),
                importe_par=acteur,
                lancer_async=True,
                continuer_malgre_doublon=validated_data.get("continuer_malgre_doublon", False),
            )
        except Exception as erreur:
            if hasattr(erreur, "message_dict"):
                raise serializers.ValidationError(erreur.message_dict) from erreur
            raise

    def to_representation(self, instance):
        return ImportOfficielDetailSerializer(instance, context=self.context).data


class CorrespondanceColonneInputSerializer(serializers.Serializer):
    """Entrée unitaire de correspondance envoyée par le frontend."""

    champ_cible = serializers.CharField(max_length=120, trim_whitespace=True)
    colonne_source = serializers.CharField(max_length=255, trim_whitespace=True)


class ValiderCorrespondanceImportSerializer(serializers.Serializer):
    """Validation des correspondances d'un import.

    Le frontend peut aussi envoyer ligne_entete/premiere_ligne_donnees dans
    parametres_lecture quand l'utilisateur corrige la détection automatique.
    """

    correspondances = CorrespondanceColonneInputSerializer(many=True)
    parametres_lecture = serializers.DictField(required=False)

    def validate_correspondances(self, correspondances):
        if not correspondances:
            raise serializers.ValidationError("Au moins une correspondance est obligatoire.")
        return correspondances

    def validate_parametres_lecture(self, parametres):
        if not parametres:
            return {}

        erreurs = {}
        for champ in ["ligne_entete", "premiere_ligne_donnees"]:
            if champ in parametres and parametres[champ] not in (None, ""):
                try:
                    valeur = int(parametres[champ])
                except (TypeError, ValueError):
                    erreurs[champ] = "La valeur doit être un entier."
                    continue
                if valeur <= 0:
                    erreurs[champ] = "La valeur doit être supérieure à zéro."
                else:
                    parametres[champ] = valeur

        ligne_entete = parametres.get("ligne_entete")
        premiere_ligne = parametres.get("premiere_ligne_donnees")
        if ligne_entete and premiere_ligne and premiere_ligne <= ligne_entete:
            erreurs["premiere_ligne_donnees"] = "La première ligne de données doit venir après l'entête."

        if erreurs:
            raise serializers.ValidationError(erreurs)
        return parametres

    def save(self, **kwargs):
        import_id = self.context.get("import_id")
        if not import_id:
            raise serializers.ValidationError({"import": "Identifiant d'import manquant."})

        request = self.context.get("request")
        acteur = getattr(request, "user", None) if request else None
        if acteur is not None and not getattr(acteur, "is_authenticated", False):
            acteur = None

        return CorrespondanceColonneImportService.valider_correspondance(
            import_id=import_id,
            correspondances=self.validated_data["correspondances"],
            parametres_lecture=self.validated_data.get("parametres_lecture") or {},
            confirme_par=acteur,
            lancer_async=True,
        )


class LigneImportSerializer(serializers.ModelSerializer):
    """Ligne d'import affichable au frontend après validation."""

    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)

    class Meta:
        model = LigneImport
        fields = [
            "id",
            "import_officiel",
            "numero_ligne",
            "donnees_brutes",
            "donnees_normalisees",
            "statut",
            "statut_libelle",
            "message_statut",
        ]
        read_only_fields = fields


class ErreurImportSerializer(serializers.ModelSerializer):
    """Erreur ou avertissement détecté sur une ligne d'import."""

    numero_ligne = serializers.IntegerField(source="ligne_import.numero_ligne", read_only=True)
    type_erreur_libelle = serializers.CharField(source="get_type_erreur_display", read_only=True)
    gravite_libelle = serializers.CharField(source="get_gravite_display", read_only=True)

    class Meta:
        model = ErreurImport
        fields = [
            "id",
            "import_officiel",
            "ligne_import",
            "numero_ligne",
            "champ_cible",
            "colonne_source",
            "type_erreur",
            "type_erreur_libelle",
            "gravite",
            "gravite_libelle",
            "message",
            "valeur_recue",
            "code_erreur",
        ]
        read_only_fields = fields


class AnnulerImportSerializer(serializers.Serializer):
    """Entrée pour annuler un import officiel."""

    message = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def save(self, **kwargs):
        import_id = self.context.get("import_id")
        if not import_id:
            raise serializers.ValidationError({"import": "Identifiant d'import manquant."})

        request = self.context.get("request")
        acteur = getattr(request, "user", None) if request else None
        if acteur is not None and not getattr(acteur, "is_authenticated", False):
            acteur = None

        return ImportOfficielService.annuler(
            import_id,
            acteur=acteur,
            message=self.validated_data.get("message", ""),
        )


class ProgressionImportSerializer(serializers.Serializer):
    """Progression temporaire stockée dans Redis/cache."""

    import_id = serializers.IntegerField(read_only=True)
    operation = serializers.CharField(read_only=True)
    pourcentage = serializers.IntegerField(read_only=True)
    message = serializers.CharField(read_only=True)
    updated_at = serializers.CharField(read_only=True, required=False)
