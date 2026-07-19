from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ActeurViewSet,
    AffectationActeurViewSet,
    AffectationPermissionViewSet,
    AffectationRoleViewSet,
    DelegationActeurViewSet,
    DemandePermissionViewSet,
    PermissionViewSet,
    RolePermissionViewSet,
    RoleViewSet,
    VerificationPermissionViewSet,
)

app_name = "accounts"

router = DefaultRouter()
router.register(r"acteurs", ActeurViewSet, basename="acteur")
router.register(r"roles", RoleViewSet, basename="role")
router.register(r"permissions", PermissionViewSet, basename="permission")
router.register(r"role-permissions", RolePermissionViewSet, basename="role-permission")
router.register(r"affectations-acteurs", AffectationActeurViewSet, basename="affectation-acteur")
router.register(r"affectation-roles", AffectationRoleViewSet, basename="affectation-role")
router.register(r"affectation-permissions", AffectationPermissionViewSet, basename="affectation-permission")
router.register(r"demandes-permissions", DemandePermissionViewSet, basename="demande-permission")
router.register(r"delegations-acteurs", DelegationActeurViewSet, basename="delegation-acteur")
router.register(r"verification-permission", VerificationPermissionViewSet, basename="verification-permission")

urlpatterns = [
    path("", include(router.urls)),
]
