from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from sessions_app.models import SessionImmersion

from .models import (
    Acteur,
    AffectationActeur,
    AffectationPermission,
    AffectationRole,
    DelegationActeur,
    DemandePermission,
    Permission,
    Role,
    RolePermission,
)
from .service import (
    ActeurService,
    AffectationActeurService,
    AffectationPermissionService,
    AffectationRoleService,
    DelegationActeurService,
    DemandePermissionService,
    PermissionService,
    RolePermissionService,
    RoleService,
)


def _convertir_erreur_django(exception):
    """Convertit une ValidationError Django en ValidationError DRF."""

    if hasattr(exception, "message_dict"):
        raise serializers.ValidationError(exception.message_dict)
    if hasattr(exception, "messages"):
        raise serializers.ValidationError(exception.messages)
    raise serializers.ValidationError(str(exception))


def acteurs_actifs_queryset():
    return Acteur.objects.filter(deleted_at__isnull=True)


def roles_actifs_queryset():
    return Role.objects.filter(deleted_at__isnull=True)


def permissions_actives_queryset():
    return Permission.objects.filter(deleted_at__isnull=True)


def affectations_actives_queryset():
    return AffectationActeur.objects.filter(deleted_at__isnull=True)


def sessions_actives_queryset():
    return SessionImmersion.objects.filter(deleted_at__isnull=True)


class ActeurResumeSerializer(serializers.ModelSerializer):
    nom_complet = serializers.CharField(read_only=True)

    class Meta:
        model = Acteur
        fields = [
            "id",
            "username",
            "nom_complet",
            "email",
            "telephone",
            "statut",
        ]
        read_only_fields = fields


class ActeurListSerializer(serializers.ModelSerializer):
    nom_complet = serializers.CharField(read_only=True)

    class Meta:
        model = Acteur
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "nom_complet",
            "email",
            "telephone",
            "titre",
            "organisation",
            "statut",
        ]
        read_only_fields = fields


class ActeurDetailSerializer(serializers.ModelSerializer):
    nom_complet = serializers.CharField(read_only=True)

    class Meta:
        model = Acteur
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "nom_complet",
            "email",
            "telephone",
            "titre",
            "organisation",
            "statut",
        ]
        read_only_fields = fields


class RoleContexteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    libelle = serializers.CharField()
    niveau = serializers.IntegerField()
    perimetre_autorise = serializers.CharField()


class SessionContexteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    nom = serializers.CharField()
    statut = serializers.CharField()
    date_debut = serializers.DateField()
    date_fin = serializers.DateField()


class AffectationContexteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    est_permanente = serializers.BooleanField()
    est_par_defaut = serializers.BooleanField()
    niveau_affectation = serializers.CharField()
    region_code = serializers.CharField(allow_blank=True)
    centre_id = serializers.IntegerField(allow_null=True)
    date_debut = serializers.DateField()
    date_fin = serializers.DateField(allow_null=True)
    statut = serializers.CharField()
    session = SessionContexteSerializer(allow_null=True)
    roles = RoleContexteSerializer(many=True)
    permissions = serializers.ListField(child=serializers.CharField())


class ContexteActeurSerializer(serializers.Serializer):
    acteur = ActeurDetailSerializer()
    affectation_courante = AffectationContexteSerializer(allow_null=True)
    nombre_affectations_actives = serializers.IntegerField()
    peut_changer_affectation = serializers.BooleanField()


class ListeAffectationsActeurSerializer(serializers.Serializer):
    affectation_par_defaut_id = serializers.IntegerField(allow_null=True)
    nombre_affectations_actives = serializers.IntegerField()
    affectations = AffectationContexteSerializer(many=True)


class ActeurCreateSerializer(serializers.ModelSerializer):
    """Création d'un acteur interne.

    Le mot de passe n'est pas reçu depuis l'API. Le service applique le mot de passe
    temporaire par défaut et déclenche l'email de bienvenue via Celery.
    """

    username = serializers.CharField(required=False, allow_blank=True)
    telephone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    titre = serializers.CharField(required=False, allow_blank=True)
    organisation = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Acteur
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "telephone",
            "titre",
            "organisation",
            "statut",
        ]
        read_only_fields = ["id", "statut"]

    def create(self, validated_data):
        request = self.context.get("request")
        created_by = getattr(request, "user", None)
        if not getattr(created_by, "is_authenticated", False):
            created_by = None

        try:
            return ActeurService.creer_acteur(
                email=validated_data["email"],
                first_name=validated_data["first_name"],
                last_name=validated_data["last_name"],
                username=validated_data.get("username"),
                telephone=validated_data.get("telephone"),
                titre=validated_data.get("titre", ""),
                organisation=validated_data.get("organisation", ""),
                created_by=created_by,
                envoyer_email_bienvenue=True,
            )
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class ActeurUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Acteur
        fields = [
            "first_name",
            "last_name",
            "telephone",
            "titre",
            "organisation",
        ]
        extra_kwargs = {
            "first_name": {"required": False},
            "last_name": {"required": False},
            "telephone": {"required": False, "allow_blank": True, "allow_null": True},
            "titre": {"required": False, "allow_blank": True},
            "organisation": {"required": False, "allow_blank": True},
        }

    def update(self, instance, validated_data):
        try:
            return ActeurService.modifier_profil(instance, **validated_data)
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class ChangementMotDePasseSerializer(serializers.Serializer):
    ancien_mot_de_passe = serializers.CharField(write_only=True, required=False, allow_blank=True)
    nouveau_mot_de_passe = serializers.CharField(write_only=True, min_length=8)
    confirmation_mot_de_passe = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs["nouveau_mot_de_passe"] != attrs["confirmation_mot_de_passe"]:
            raise serializers.ValidationError({"confirmation_mot_de_passe": "Les mots de passe ne correspondent pas."})

        acteur = self.context.get("acteur") or getattr(self.context.get("request"), "user", None)
        ancien = attrs.get("ancien_mot_de_passe")
        if getattr(acteur, "is_authenticated", False) and acteur.has_usable_password() and ancien:
            if not acteur.check_password(ancien):
                raise serializers.ValidationError({"ancien_mot_de_passe": "Ancien mot de passe incorrect."})
        return attrs

    def save(self, **kwargs):
        acteur = self.context.get("acteur") or getattr(self.context.get("request"), "user", None)
        if not getattr(acteur, "is_authenticated", False):
            raise serializers.ValidationError("Acteur non authentifié.")

        try:
            return ActeurService.changer_mot_de_passe(acteur, self.validated_data["nouveau_mot_de_passe"])
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = [
            "id",
            "code",
            "libelle",
            "description",
            "niveau",
            "perimetre_autorise",
            "est_systeme",
            "est_modifiable",
            "statut",
        ]
        read_only_fields = ["id", "code", "est_systeme", "est_modifiable", "statut"]


class RoleCreateSerializer(serializers.ModelSerializer):
    """Création d'un rôle personnalisé.

    Le code du rôle est généré par le service à partir du libellé.
    """

    class Meta:
        model = Role
        fields = [
            "id",
            "code",
            "libelle",
            "description",
            "niveau",
            "perimetre_autorise",
            "est_systeme",
            "est_modifiable",
            "statut",
        ]
        read_only_fields = ["id", "code", "est_systeme", "est_modifiable", "statut"]

    def create(self, validated_data):
        try:
            return RoleService.creer_role_personnalise(
                libelle=validated_data["libelle"],
                niveau=validated_data["niveau"],
                perimetre_autorise=validated_data["perimetre_autorise"],
                description=validated_data.get("description", ""),
            )
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = [
            "id",
            "code",
            "libelle",
            "module",
            "description",
            "est_systeme",
            "statut",
        ]
        read_only_fields = fields


class PermissionSystemeCreateSerializer(serializers.ModelSerializer):
    """Création technique d'une permission système existant dans le backend."""

    class Meta:
        model = Permission
        fields = [
            "id",
            "code",
            "libelle",
            "module",
            "description",
            "est_systeme",
            "statut",
        ]
        read_only_fields = ["id", "est_systeme", "statut"]

    def create(self, validated_data):
        try:
            return PermissionService.creer_permission_systeme(
                code=validated_data["code"],
                libelle=validated_data["libelle"],
                module=validated_data["module"],
                description=validated_data.get("description", ""),
            )
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class RolePermissionSerializer(serializers.ModelSerializer):
    role_id = serializers.PrimaryKeyRelatedField(source="role", queryset=roles_actifs_queryset())
    permission_id = serializers.PrimaryKeyRelatedField(source="permission", queryset=permissions_actives_queryset())
    role_code = serializers.CharField(source="role.code", read_only=True)
    permission_code = serializers.CharField(source="permission.code", read_only=True)
    permission_libelle = serializers.CharField(source="permission.libelle", read_only=True)

    class Meta:
        model = RolePermission
        fields = [
            "id",
            "role_id",
            "role_code",
            "permission_id",
            "permission_code",
            "permission_libelle",
            "est_delegable",
            "perimetre_delegation_max",
            "statut",
        ]
        read_only_fields = ["id", "role_code", "permission_code", "permission_libelle", "statut"]

    def create(self, validated_data):
        try:
            return RolePermissionService.ajouter_permission(
                validated_data["role"],
                validated_data["permission"],
                est_delegable=validated_data.get("est_delegable", False),
                perimetre_delegation_max=validated_data.get("perimetre_delegation_max", ""),
            )
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class AffectationActeurSerializer(serializers.ModelSerializer):
    acteur_id = serializers.PrimaryKeyRelatedField(source="acteur", queryset=acteurs_actifs_queryset())
    acteur = ActeurResumeSerializer(read_only=True)
    session_id = serializers.PrimaryKeyRelatedField(
        source="session",
        queryset=sessions_actives_queryset(),
        required=False,
        allow_null=True,
    )
    session_code = serializers.CharField(source="session.code", read_only=True)
    session_nom = serializers.CharField(source="session.nom", read_only=True)
    affecte_par_id = serializers.PrimaryKeyRelatedField(
        source="affecte_par",
        queryset=acteurs_actifs_queryset(),
        required=False,
        allow_null=True,
    )
    affecte_par = ActeurResumeSerializer(read_only=True)
    est_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = AffectationActeur
        fields = [
            "id",
            "acteur_id",
            "acteur",
            "session_id",
            "session_code",
            "session_nom",
            "niveau_affectation",
            "region_code",
            "centre_id",
            "date_debut",
            "date_fin",
            "statut",
            "affecte_par_id",
            "affecte_par",
            "est_active",
        ]
        read_only_fields = ["id", "acteur", "session_code", "session_nom", "statut", "affecte_par", "est_active"]

    def create(self, validated_data):
        try:
            return AffectationActeurService.creer_affectation(
                acteur=validated_data["acteur"],
                niveau_affectation=validated_data["niveau_affectation"],
                session=validated_data.get("session"),
                region_code=validated_data.get("region_code", ""),
                centre_id=validated_data.get("centre_id"),
                date_debut=validated_data.get("date_debut"),
                date_fin=validated_data.get("date_fin"),
                affecte_par=validated_data.get("affecte_par"),
            )
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class AffectationRoleSerializer(serializers.ModelSerializer):
    affectation_acteur_id = serializers.PrimaryKeyRelatedField(
        source="affectation_acteur",
        queryset=affectations_actives_queryset(),
    )
    role_id = serializers.PrimaryKeyRelatedField(source="role", queryset=roles_actifs_queryset())
    role = RoleSerializer(read_only=True)
    attribue_par_id = serializers.PrimaryKeyRelatedField(
        source="attribue_par",
        queryset=acteurs_actifs_queryset(),
        required=False,
        allow_null=True,
    )
    attribue_par = ActeurResumeSerializer(read_only=True)
    est_actif = serializers.BooleanField(read_only=True)

    class Meta:
        model = AffectationRole
        fields = [
            "id",
            "affectation_acteur_id",
            "role_id",
            "role",
            "date_attribution",
            "date_expiration",
            "statut",
            "attribue_par_id",
            "attribue_par",
            "est_actif",
        ]
        read_only_fields = ["id", "role", "statut", "attribue_par", "est_actif"]

    def create(self, validated_data):
        try:
            return AffectationRoleService.attribuer_role(
                validated_data["affectation_acteur"],
                validated_data["role"],
                attribue_par=validated_data.get("attribue_par"),
                date_attribution=validated_data.get("date_attribution"),
                date_expiration=validated_data.get("date_expiration"),
            )
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class AffectationPermissionSerializer(serializers.ModelSerializer):
    affectation_acteur_id = serializers.PrimaryKeyRelatedField(
        source="affectation_acteur",
        queryset=affectations_actives_queryset(),
    )
    permission_id = serializers.PrimaryKeyRelatedField(source="permission", queryset=permissions_actives_queryset())
    permission = PermissionSerializer(read_only=True)
    attribue_par_id = serializers.PrimaryKeyRelatedField(
        source="attribue_par",
        queryset=acteurs_actifs_queryset(),
        required=False,
        allow_null=True,
    )
    attribue_par = ActeurResumeSerializer(read_only=True)
    est_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = AffectationPermission
        fields = [
            "id",
            "affectation_acteur_id",
            "permission_id",
            "permission",
            "date_attribution",
            "date_expiration",
            "est_delegable",
            "motif",
            "statut",
            "attribue_par_id",
            "attribue_par",
            "est_active",
        ]
        read_only_fields = ["id", "permission", "statut", "attribue_par", "est_active"]

    def create(self, validated_data):
        try:
            return AffectationPermissionService.attribuer_permission_directe(
                validated_data["affectation_acteur"],
                validated_data["permission"],
                attribue_par=validated_data.get("attribue_par"),
                date_attribution=validated_data.get("date_attribution"),
                date_expiration=validated_data.get("date_expiration"),
                est_delegable=validated_data.get("est_delegable", False),
                motif=validated_data.get("motif", ""),
            )
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class DemandePermissionSerializer(serializers.ModelSerializer):
    acteur_id = serializers.PrimaryKeyRelatedField(
        source="acteur",
        queryset=acteurs_actifs_queryset(),
        required=False,
    )
    acteur = ActeurResumeSerializer(read_only=True)
    affectation_acteur_id = serializers.PrimaryKeyRelatedField(
        source="affectation_acteur",
        queryset=affectations_actives_queryset(),
        required=False,
        allow_null=True,
    )
    permission_id = serializers.PrimaryKeyRelatedField(source="permission", queryset=permissions_actives_queryset())
    permission = PermissionSerializer(read_only=True)
    decideur = ActeurResumeSerializer(read_only=True)

    class Meta:
        model = DemandePermission
        fields = [
            "id",
            "acteur_id",
            "acteur",
            "affectation_acteur_id",
            "permission_id",
            "permission",
            "justification",
            "statut",
            "date_demande",
            "date_decision",
            "decideur",
            "motif_decision",
        ]
        read_only_fields = [
            "id",
            "acteur",
            "permission",
            "statut",
            "date_demande",
            "date_decision",
            "decideur",
            "motif_decision",
        ]

    def create(self, validated_data):
        request = self.context.get("request")
        acteur = validated_data.get("acteur") or getattr(request, "user", None)
        if not getattr(acteur, "is_authenticated", False):
            raise serializers.ValidationError({"acteur_id": "L'acteur demandeur est obligatoire."})

        try:
            return DemandePermissionService.soumettre_demande(
                acteur=acteur,
                permission=validated_data["permission"],
                justification=validated_data["justification"],
                affectation=validated_data.get("affectation_acteur"),
            )
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class TraitementDemandePermissionSerializer(serializers.Serializer):
    motif_decision = serializers.CharField(required=False, allow_blank=True)
    date_expiration = serializers.DateField(required=False, allow_null=True)


class DelegationActeurSerializer(serializers.ModelSerializer):
    acteur_source_id = serializers.PrimaryKeyRelatedField(source="acteur_source", queryset=acteurs_actifs_queryset())
    acteur_source = ActeurResumeSerializer(read_only=True)
    acteur_cible_id = serializers.PrimaryKeyRelatedField(source="acteur_cible", queryset=acteurs_actifs_queryset())
    acteur_cible = ActeurResumeSerializer(read_only=True)
    affectation_acteur_id = serializers.PrimaryKeyRelatedField(
        source="affectation_acteur",
        queryset=affectations_actives_queryset(),
    )
    role_id = serializers.PrimaryKeyRelatedField(
        source="role",
        queryset=roles_actifs_queryset(),
        required=False,
        allow_null=True,
    )
    permission_id = serializers.PrimaryKeyRelatedField(
        source="permission",
        queryset=permissions_actives_queryset(),
        required=False,
        allow_null=True,
    )
    role = RoleSerializer(read_only=True)
    permission = PermissionSerializer(read_only=True)
    est_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = DelegationActeur
        fields = [
            "id",
            "acteur_source_id",
            "acteur_source",
            "acteur_cible_id",
            "acteur_cible",
            "affectation_acteur_id",
            "role_id",
            "role",
            "permission_id",
            "permission",
            "type_delegation",
            "date_debut",
            "date_fin",
            "motif",
            "statut",
            "est_active",
        ]
        read_only_fields = ["id", "acteur_source", "acteur_cible", "role", "permission", "statut", "est_active"]

    def create(self, validated_data):
        try:
            return DelegationActeurService.creer_delegation(
                acteur_source=validated_data["acteur_source"],
                acteur_cible=validated_data["acteur_cible"],
                affectation_acteur=validated_data["affectation_acteur"],
                type_delegation=validated_data["type_delegation"],
                date_fin=validated_data["date_fin"],
                role=validated_data.get("role"),
                permission=validated_data.get("permission"),
                motif=validated_data.get("motif", ""),
                date_debut=validated_data.get("date_debut"),
            )
        except DjangoValidationError as exception:
            _convertir_erreur_django(exception)


class VerificationPermissionSerializer(serializers.Serializer):
    acteur_id = serializers.IntegerField()
    affectation_id = serializers.IntegerField(required=False)
    permission_code = serializers.CharField(max_length=120)
    session_id = serializers.IntegerField(required=False, allow_null=True)
    region_code = serializers.CharField(required=False, allow_blank=True)
    centre_id = serializers.IntegerField(required=False, allow_null=True)
