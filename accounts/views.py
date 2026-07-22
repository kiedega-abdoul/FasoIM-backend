from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from sessions_app.models import SessionImmersion
from affectations.models import CentreImmersion, RegionImmersion

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
from .permissions import (
    EstActeurActif,
    PeutVoirSonProfilOuPermissionActeur,
    PermissionActeur,
    PermissionAffectationActeur,
    PermissionAffectationPermission,
    PermissionAffectationRole,
    PermissionDelegationActeur,
    PermissionDemandePermission,
    PermissionPermissionSysteme,
    PermissionRole,
    PermissionRolePermission,
)
from .repository import (
    ActeurRepository,
    AffectationActeurRepository,
    AffectationPermissionRepository,
    AffectationRoleRepository,
    DelegationActeurRepository,
    DemandePermissionRepository,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
)
from .serializers import (
    ActeurCreateSerializer,
    ActeurDetailSerializer,
    ActeurListSerializer,
    ActeurUpdateSerializer,
    AffectationActeurSerializer,
    AffectationPermissionSerializer,
    AffectationRoleSerializer,
    ChangementMotDePasseSerializer,
    ContexteActeurSerializer,
    DelegationActeurSerializer,
    DemandePermissionSerializer,
    PermissionSerializer,
    ListeAffectationsActeurSerializer,
    PermissionSystemeCreateSerializer,
    RoleCreateSerializer,
    RolePermissionSerializer,
    RoleSerializer,
    TraitementDemandePermissionSerializer,
    VerificationPermissionSerializer,
)
from .service import (
    ActeurService,
    AffectationActeurService,
    AffectationPermissionService,
    AffectationRoleService,
    ContexteActeurService,
    ControleAccesService,
    DelegationActeurService,
    DemandePermissionService,
    PermissionService,
    RolePermissionService,
    RoleService,
)


def convertir_erreur_service(exception):
    """Convertit une ValidationError Django en ValidationError DRF."""

    if hasattr(exception, "message_dict"):
        raise ValidationError(exception.message_dict)
    if hasattr(exception, "messages"):
        raise ValidationError(exception.messages)
    raise ValidationError(str(exception))


class AccountsViewSetBase(viewsets.ModelViewSet):
    """Base légère des ViewSets du module accounts."""

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["acteur_connecte"] = self.request.user
        return context

    def reponse_action(self, message, extra=None, statut=status.HTTP_200_OK):
        payload = {"detail": message}
        if extra:
            payload.update(extra)
        return Response(payload, status=statut)


class AccountsReadCreateViewSetBase(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Base pour les ressources qui se créent mais ne se modifient pas librement."""

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["acteur_connecte"] = self.request.user
        return context

    def reponse_action(self, message, extra=None, statut=status.HTTP_200_OK):
        payload = {"detail": message}
        if extra:
            payload.update(extra)
        return Response(payload, status=statut)


class ActeurViewSet(AccountsViewSetBase):
    """API de gestion des acteurs internes FasoIM."""

    permission_classes = [EstActeurActif, PermissionActeur]
    serializer_class = ActeurDetailSerializer
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        terme = self.request.query_params.get("q") or self.request.query_params.get("recherche")
        statut_filtre = self.request.query_params.get("statut")
        queryset = ActeurRepository.rechercher(terme=terme, statut=statut_filtre)

        organisation = self.request.query_params.get("organisation")
        if organisation:
            queryset = queryset.filter(organisation__icontains=organisation)

        titre = self.request.query_params.get("titre")
        if titre:
            queryset = queryset.filter(titre__icontains=titre)

        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return ActeurListSerializer
        if self.action == "create":
            return ActeurCreateSerializer
        if self.action in {"update", "partial_update"}:
            return ActeurUpdateSerializer
        if self.action == "changer_mot_de_passe":
            return ChangementMotDePasseSerializer
        return ActeurDetailSerializer

    def perform_destroy(self, instance):
        ActeurService.desactiver_acteur(instance, auteur=self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return self.reponse_action("Acteur désactivé avec succès.")

    @action(detail=True, methods=["post"])
    def desactiver(self, request, pk=None):
        acteur = self.get_object()
        try:
            ActeurService.desactiver_acteur(acteur, auteur=request.user)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return self.reponse_action("Acteur désactivé avec succès.")

    @action(detail=True, methods=["post"])
    def reactiver(self, request, pk=None):
        acteur = self.get_object()
        try:
            acteur = ActeurService.reactiver_acteur(acteur, auteur=request.user)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        serializer = ActeurDetailSerializer(acteur, context=self.get_serializer_context())
        return self.reponse_action("Acteur réactivé avec succès.", {"acteur": serializer.data})

    @action(detail=False, methods=["get"], permission_classes=[EstActeurActif])
    def me(self, request):
        serializer = ActeurDetailSerializer(request.user, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[EstActeurActif],
        url_path="mon-contexte",
    )
    def mon_contexte(self, request):
        contexte = ContexteActeurService.construire_contexte(request.user)
        serializer = ContexteActeurSerializer(contexte)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[EstActeurActif],
        url_path="mes-affectations",
    )
    def mes_affectations(self, request):
        donnees = ContexteActeurService.construire_liste_affectations(request.user)
        serializer = ListeAffectationsActeurSerializer(donnees)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[EstActeurActif],
        url_path=r"contexte-affectation/(?P<affectation_id>[^/.]+)",
    )
    def contexte_affectation(self, request, affectation_id=None):
        try:
            contexte = ContexteActeurService.construire_contexte(
                request.user,
                affectation=affectation_id,
            )
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)

        serializer = ContexteActeurSerializer(contexte)
        return Response(serializer.data)

    @action(detail=False, methods=["patch"], permission_classes=[EstActeurActif])
    def mon_profil(self, request):
        serializer = ActeurUpdateSerializer(request.user, data=request.data, partial=True, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        acteur = serializer.save()
        return Response(ActeurDetailSerializer(acteur, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["post"], permission_classes=[EstActeurActif])
    def changer_mot_de_passe(self, request):
        serializer = ChangementMotDePasseSerializer(data=request.data, context={**self.get_serializer_context(), "acteur": request.user})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.reponse_action("Mot de passe modifié avec succès.")

    @action(detail=True, methods=["post"])
    def suppression_logique_cascade(self, request, pk=None):
        acteur = self.get_object()
        try:
            ActeurService.supprimer_logiquement_async(acteur, auteur=request.user)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return self.reponse_action("Suppression logique en cascade planifiée.", statut=status.HTTP_202_ACCEPTED)


class RoleViewSet(AccountsViewSetBase):
    """API de gestion des rôles accounts."""

    permission_classes = [EstActeurActif, PermissionRole]
    serializer_class = RoleSerializer
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = RoleRepository.actifs()

        niveau = self.request.query_params.get("niveau")
        if niveau:
            queryset = queryset.filter(niveau=niveau)

        perimetre = self.request.query_params.get("perimetre") or self.request.query_params.get("perimetre_autorise")
        if perimetre:
            queryset = queryset.filter(perimetre_autorise=perimetre)

        est_systeme = self.request.query_params.get("est_systeme")
        if est_systeme in {"true", "1", "oui"}:
            queryset = queryset.filter(est_systeme=True)
        elif est_systeme in {"false", "0", "non"}:
            queryset = queryset.filter(est_systeme=False)

        return queryset.order_by("niveau", "code")

    def get_serializer_class(self):
        if self.action == "create":
            return RoleCreateSerializer
        return RoleSerializer

    def perform_destroy(self, instance):
        RoleService.desactiver_role(instance)

    def destroy(self, request, *args, **kwargs):
        role = self.get_object()
        try:
            self.perform_destroy(role)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return self.reponse_action("Rôle désactivé avec succès.")

    @action(detail=True, methods=["post"])
    def desactiver(self, request, pk=None):
        role = self.get_object()
        try:
            RoleService.desactiver_role(role)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return self.reponse_action("Rôle désactivé avec succès.")

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[EstActeurActif],
        url_path="attribuables",
    )
    def attribuables(self, request):
        affectation_id = request.query_params.get("affectation_acteur_id") or request.query_params.get("affectation")
        if not affectation_id:
            raise ValidationError("Affectation obligatoire.")

        try:
            roles = RoleService.lister_roles_attribuables(request.user, affectation_id)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)

        serializer = RoleSerializer(roles, many=True, context=self.get_serializer_context())
        return Response(serializer.data)


class PermissionViewSet(AccountsReadCreateViewSetBase):
    """API du catalogue système des permissions accounts."""

    permission_classes = [EstActeurActif, PermissionPermissionSysteme]
    serializer_class = PermissionSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        module = self.request.query_params.get("module")
        if module:
            return PermissionRepository.lister_par_module(module)
        return PermissionRepository.actives().order_by("module", "code")

    def get_serializer_class(self):
        if self.action == "create":
            return PermissionSystemeCreateSerializer
        return PermissionSerializer

    @action(detail=False, methods=["get"])
    def modules(self, request):
        modules = list(
            PermissionRepository.actives()
            .exclude(module="")
            .values_list("module", flat=True)
            .distinct()
            .order_by("module")
        )
        return Response({"modules": modules})


class RolePermissionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """API de liaison entre rôles et permissions."""

    permission_classes = [EstActeurActif, PermissionRolePermission]
    serializer_class = RolePermissionSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = RolePermissionRepository.actives()

        role_id = self.request.query_params.get("role_id") or self.request.query_params.get("role")
        if role_id:
            queryset = queryset.filter(role_id=role_id)

        permission_id = self.request.query_params.get("permission_id") or self.request.query_params.get("permission")
        if permission_id:
            queryset = queryset.filter(permission_id=permission_id)

        return queryset.order_by("role__code", "permission__code")

    def destroy(self, request, *args, **kwargs):
        role_permission = self.get_object()
        try:
            RolePermissionService.retirer_permission(role_permission)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def retirer(self, request, pk=None):
        role_permission = self.get_object()
        try:
            RolePermissionService.retirer_permission(role_permission)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AffectationActeurViewSet(mixins.DestroyModelMixin, AccountsReadCreateViewSetBase):
    """API des affectations d'acteurs à un périmètre FasoIM."""

    permission_classes = [EstActeurActif, PermissionAffectationActeur]
    serializer_class = AffectationActeurSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = (
            AffectationActeurRepository.non_supprimes()
            .exclude(
                statut__in=[
                    AffectationActeur.Statut.TERMINEE,
                    AffectationActeur.Statut.ANNULEE,
                ]
            )
            .select_related("acteur", "session")
            .prefetch_related("roles_affectes__role")
        )

        acteur_id = self.request.query_params.get("acteur_id") or self.request.query_params.get("acteur")
        if acteur_id:
            queryset = queryset.filter(acteur_id=acteur_id)

        session_id = self.request.query_params.get("session_id") or self.request.query_params.get("session")
        if session_id:
            queryset = queryset.filter(session_id=session_id)

        region_code = self.request.query_params.get("region_code") or self.request.query_params.get("region")
        if region_code:
            queryset = queryset.filter(region_code__iexact=region_code)

        centre_id = self.request.query_params.get("centre_id") or self.request.query_params.get("centre")
        if centre_id:
            queryset = queryset.filter(centre_id=centre_id)

        niveau = self.request.query_params.get("niveau_affectation") or self.request.query_params.get("niveau")
        if niveau:
            queryset = queryset.filter(niveau_affectation=niveau)

        return queryset.order_by("acteur__last_name", "acteur__first_name", "niveau_affectation")

    def perform_create(self, serializer):
        serializer.save(affecte_par=self.request.user)

    @action(detail=False, methods=["get"], url_path="references")
    def references(self, request):
        """Référentiels lisibles nécessaires au formulaire d'affectation.

        Cette action évite de demander à l'utilisateur des identifiants
        techniques et reste protégée par la permission affecter_acteur_session.
        """

        region_code = (request.query_params.get("region_code") or "").strip()

        sessions = list(
            SessionImmersion.objects.filter(
                deleted_at__isnull=True,
                statut__in=AffectationActeur.SESSION_STATUTS_ACTIFS,
            )
            .order_by("-date_debut", "nom")
            .values("id", "code", "nom", "statut", "date_debut", "date_fin")
        )

        regions = list(
            RegionImmersion.objects.filter(
                deleted_at__isnull=True,
                statut=RegionImmersion.Statut.ACTIVE,
            )
            .order_by("nom")
            .values("id", "code", "nom")
        )

        centres_queryset = CentreImmersion.objects.filter(
            deleted_at__isnull=True,
            statut=CentreImmersion.Statut.ACTIF,
        ).select_related("region")

        if region_code:
            centres_queryset = centres_queryset.filter(region__code__iexact=region_code)

        centres = [
            {
                "id": centre.id,
                "code": centre.code,
                "nom": centre.nom,
                "ville": centre.ville,
                "province": centre.province,
                "region_code": centre.region.code,
                "region_nom": centre.region.nom,
            }
            for centre in centres_queryset.order_by("region__nom", "nom")
        ]

        return Response(
            {
                "sessions": sessions,
                "regions": regions,
                "centres": centres,
            }
        )

    def destroy(self, request, *args, **kwargs):
        affectation = self.get_object()
        try:
            AffectationActeurService.terminer_affectation(affectation)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return self.reponse_action("Affectation retirée avec succès.")

    @action(detail=True, methods=["post"])
    def suspendre(self, request, pk=None):
        affectation = self.get_object()
        try:
            affectation = AffectationActeurService.suspendre_affectation(affectation)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        serializer = AffectationActeurSerializer(affectation, context=self.get_serializer_context())
        return self.reponse_action("Affectation suspendue avec succès.", {"affectation": serializer.data})

    @action(detail=True, methods=["post"])
    def reactiver(self, request, pk=None):
        affectation = self.get_object()
        try:
            affectation = AffectationActeurService.reactiver_affectation(affectation)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        serializer = AffectationActeurSerializer(affectation, context=self.get_serializer_context())
        return self.reponse_action("Affectation réactivée avec succès.", {"affectation": serializer.data})

    @action(detail=True, methods=["post"])
    def retirer(self, request, pk=None):
        affectation = self.get_object()
        try:
            AffectationActeurService.terminer_affectation(affectation)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return self.reponse_action("Affectation retirée avec succès.")


class AffectationRoleViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """API des rôles attribués à une affectation."""

    permission_classes = [EstActeurActif, PermissionAffectationRole]
    serializer_class = AffectationRoleSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = AffectationRoleRepository.actifs()

        affectation_id = self.request.query_params.get("affectation_acteur_id") or self.request.query_params.get("affectation")
        if affectation_id:
            queryset = queryset.filter(affectation_acteur_id=affectation_id)

        role_id = self.request.query_params.get("role_id") or self.request.query_params.get("role")
        if role_id:
            queryset = queryset.filter(role_id=role_id)

        return queryset.order_by("affectation_acteur_id", "role__code")

    def destroy(self, request, *args, **kwargs):
        affectation_role = self.get_object()
        try:
            AffectationRoleService.retirer_role(affectation_role)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def retirer(self, request, pk=None):
        affectation_role = self.get_object()
        try:
            AffectationRoleService.retirer_role(affectation_role)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AffectationPermissionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """API des permissions directes attribuées à une affectation."""

    permission_classes = [EstActeurActif, PermissionAffectationPermission]
    serializer_class = AffectationPermissionSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = AffectationPermissionRepository.actives()

        affectation_id = self.request.query_params.get("affectation_acteur_id") or self.request.query_params.get("affectation")
        if affectation_id:
            queryset = queryset.filter(affectation_acteur_id=affectation_id)

        permission_id = self.request.query_params.get("permission_id") or self.request.query_params.get("permission")
        if permission_id:
            queryset = queryset.filter(permission_id=permission_id)

        return queryset.order_by("affectation_acteur_id", "permission__code")

    def destroy(self, request, *args, **kwargs):
        affectation_permission = self.get_object()
        try:
            AffectationPermissionService.retirer_permission_directe(affectation_permission)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def retirer(self, request, pk=None):
        affectation_permission = self.get_object()
        try:
            AffectationPermissionService.retirer_permission_directe(affectation_permission)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DemandePermissionViewSet(AccountsReadCreateViewSetBase):
    """API des demandes de permissions supplémentaires."""

    permission_classes = [EstActeurActif, PermissionDemandePermission]
    serializer_class = DemandePermissionSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = DemandePermissionRepository.non_supprimes()

        acteur_id = self.request.query_params.get("acteur_id") or self.request.query_params.get("acteur")
        if acteur_id:
            queryset = queryset.filter(acteur_id=acteur_id)

        statut_filtre = self.request.query_params.get("statut")
        if statut_filtre:
            queryset = queryset.filter(statut=statut_filtre)

        permission_id = self.request.query_params.get("permission_id") or self.request.query_params.get("permission")
        if permission_id:
            queryset = queryset.filter(permission_id=permission_id)

        return queryset.order_by("-date_demande", "-id")

    @action(detail=True, methods=["post"])
    def approuver(self, request, pk=None):
        demande = self.get_object()
        serializer = TraitementDemandePermissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            demande = DemandePermissionService.approuver_demande(
                demande,
                decideur=request.user,
                motif_decision=serializer.validated_data.get("motif_decision", ""),
                date_expiration=serializer.validated_data.get("date_expiration"),
            )
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return Response(DemandePermissionSerializer(demande, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def refuser(self, request, pk=None):
        demande = self.get_object()
        serializer = TraitementDemandePermissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            demande = DemandePermissionService.refuser_demande(
                demande,
                decideur=request.user,
                motif_decision=serializer.validated_data.get("motif_decision", ""),
            )
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return Response(DemandePermissionSerializer(demande, context=self.get_serializer_context()).data)


class DelegationActeurViewSet(AccountsReadCreateViewSetBase):
    """API des délégations temporaires entre acteurs."""

    permission_classes = [EstActeurActif, PermissionDelegationActeur]
    serializer_class = DelegationActeurSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = DelegationActeurRepository.non_supprimes()

        acteur_source_id = self.request.query_params.get("acteur_source_id") or self.request.query_params.get("source")
        if acteur_source_id:
            queryset = queryset.filter(acteur_source_id=acteur_source_id)

        acteur_cible_id = self.request.query_params.get("acteur_cible_id") or self.request.query_params.get("cible")
        if acteur_cible_id:
            queryset = queryset.filter(acteur_cible_id=acteur_cible_id)

        affectation_id = self.request.query_params.get("affectation_acteur_id") or self.request.query_params.get("affectation")
        if affectation_id:
            queryset = queryset.filter(affectation_acteur_id=affectation_id)

        statut_filtre = self.request.query_params.get("statut")
        if statut_filtre:
            queryset = queryset.filter(statut=statut_filtre)

        return queryset.order_by("-date_debut", "-date_fin", "-id")

    @action(detail=True, methods=["post"])
    def terminer(self, request, pk=None):
        delegation = self.get_object()
        try:
            delegation = DelegationActeurService.terminer_delegation(delegation)
        except DjangoValidationError as exception:
            convertir_erreur_service(exception)
        return Response(DelegationActeurSerializer(delegation, context=self.get_serializer_context()).data)


class VerificationPermissionViewSet(viewsets.ViewSet):
    """Endpoint technique pour vérifier une permission effective.

    Utile pendant le développement, puis pour les écrans qui veulent tester un
    droit précis sans exposer les champs internes du contrôle d'accès.
    """

    permission_classes = [EstActeurActif]

    def create(self, request):
        serializer = VerificationPermissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        acteur = ActeurRepository.get_actif_by_id(serializer.validated_data["acteur_id"])
        if not acteur:
            raise ValidationError({"acteur_id": "Acteur introuvable ou inactif."})

        affectation = None
        affectation_id = serializer.validated_data.get("affectation_id")
        if affectation_id:
            affectation = AffectationActeurRepository.get_active_by_id(affectation_id)
            if not affectation:
                raise ValidationError({"affectation_id": "Affectation active introuvable."})

        resultat = ControleAccesService.acteur_peut(
            acteur,
            serializer.validated_data["permission_code"],
            affectation=affectation,
            session_id=serializer.validated_data.get("session_id"),
            region_code=serializer.validated_data.get("region_code"),
            centre_id=serializer.validated_data.get("centre_id"),
        )

        return Response(
            {
                "autorise": resultat.autorise,
                "motif": resultat.motif,
                "affectation_id": getattr(resultat.affectation, "id", None),
            }
        )
