from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Acteur,
    AffectationActeur,
    AffectationPermission,
    AffectationRole,
    DelegationActeur,
    DemandePermission,
    Permission,
    Role,
)
from .service import (
    MOT_DE_PASSE_ACTEUR_PAR_DEFAUT,
    ActeurService,
    AffectationActeurService,
    AffectationPermissionService,
    AffectationRoleService,
    ControleAccesService,
    DelegationActeurService,
    DemandePermissionService,
    PermissionService,
    RolePermissionService,
    RoleService,
)


class AccountsServiceTests(TestCase):
    """Tests métier du module accounts.

    Ces tests valident les règles critiques : mot de passe par défaut,
    affectations, rôles, permissions directes, demandes, délégations et
    suppression logique cascade. Autrement dit, les portes blindées avant que
    quelqu'un décide d'utiliser le backend comme un cahier de brouillon.
    """

    def setUp(self):
        self.admin = Acteur.objects.create_superuser(
            username="admin",
            email="admin@fasoim.local",
            password="AdminPass123!",
            first_name="Admin",
            last_name="FasoIM",
        )

    def creer_acteur(self, username="acteur", email="acteur@fasoim.local"):
        return Acteur.objects.create_user(
            username=username,
            email=email,
            password="SecretPass123!",
            first_name=username.capitalize(),
            last_name="Test",
            statut=Acteur.Statut.ACTIF,
        )

    def creer_role_permission(self, code_permission="creer_acteur"):
        role = RoleService.creer_role_systeme(
            code="DGAS",
            libelle="DGAS",
            niveau=10,
            perimetre_autorise=Role.Perimetre.NATIONAL,
            est_modifiable=True,
        )
        permission = PermissionService.creer_permission_systeme(
            code=code_permission,
            libelle=f"Permission {code_permission}",
            module="accounts",
        )
        RolePermissionService.ajouter_permission(
            role,
            permission,
            est_delegable=True,
            perimetre_delegation_max=Role.Perimetre.NATIONAL,
        )
        return role, permission

    @patch("accounts.service.ServiceAsynchroneAccounts.envoyer_email_bienvenue_apres_commit")
    def test_creer_acteur_applique_mot_de_passe_defaut_et_planifie_email(self, mock_email):
        acteur = ActeurService.creer_acteur(
            email="moussa@fasoim.local",
            first_name="Moussa",
            last_name="Traoré",
            telephone="70000001",
            created_by=self.admin,
        )

        self.assertEqual(acteur.username, "moussa-traore")
        self.assertTrue(acteur.check_password(MOT_DE_PASSE_ACTEUR_PAR_DEFAUT))
        self.assertEqual(acteur.created_by, self.admin)
        mock_email.assert_called_once_with(acteur.id, MOT_DE_PASSE_ACTEUR_PAR_DEFAUT)

    @patch("accounts.service.ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit")
    def test_controle_acces_autorise_par_role_et_affectation_active(self, mock_cache):
        acteur = self.creer_acteur()
        role, _permission = self.creer_role_permission("creer_acteur")
        affectation = AffectationActeurService.creer_affectation(
            acteur=acteur,
            niveau_affectation=AffectationActeur.NiveauAffectation.NATIONAL,
            affecte_par=self.admin,
        )
        AffectationRoleService.attribuer_role(affectation, role, attribue_par=self.admin)

        resultat = ControleAccesService.acteur_peut(acteur, "creer_acteur")
        refus = ControleAccesService.acteur_peut(acteur, "modifier_session")

        self.assertTrue(resultat.autorise)
        self.assertEqual(resultat.affectation.id, affectation.id)
        self.assertFalse(refus.autorise)
        self.assertGreaterEqual(mock_cache.call_count, 2)

    @patch("accounts.service.ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit")
    def test_permission_directe_respecte_le_perimetre_region(self, mock_cache):
        acteur = self.creer_acteur()
        permission = PermissionService.creer_permission_systeme(
            code="lister_acteurs",
            libelle="Lister les acteurs",
            module="accounts",
        )
        affectation = AffectationActeurService.creer_affectation(
            acteur=acteur,
            niveau_affectation=AffectationActeur.NiveauAffectation.REGION,
            region_code="CENTRE",
            affecte_par=self.admin,
        )
        AffectationPermissionService.attribuer_permission_directe(
            affectation,
            permission,
            attribue_par=self.admin,
            motif="Test permission directe",
        )

        autorise = ControleAccesService.acteur_peut(acteur, "lister_acteurs", region_code="CENTRE")
        refuse = ControleAccesService.acteur_peut(acteur, "lister_acteurs", region_code="HAUTS_BASSINS")

        self.assertTrue(autorise.autorise)
        self.assertFalse(refuse.autorise)
        self.assertGreaterEqual(mock_cache.call_count, 2)

    @patch("accounts.service.ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit")
    def test_demande_permission_approuvee_cree_permission_directe(self, _mock_cache):
        acteur = self.creer_acteur()
        permission = PermissionService.creer_permission_systeme(
            code="consulter_acteur",
            libelle="Consulter acteur",
            module="accounts",
        )
        affectation = AffectationActeurService.creer_affectation(
            acteur=acteur,
            niveau_affectation=AffectationActeur.NiveauAffectation.NATIONAL,
            affecte_par=self.admin,
        )

        demande = DemandePermissionService.soumettre_demande(
            acteur=acteur,
            affectation=affectation,
            permission=permission,
            justification="Besoin temporaire pour le test.",
        )
        demande = DemandePermissionService.approuver_demande(
            demande,
            decideur=self.admin,
            motif_decision="Accord test.",
        )

        self.assertEqual(demande.statut, DemandePermission.Statut.APPROUVEE)
        self.assertTrue(
            AffectationPermission.objects.filter(
                affectation_acteur=affectation,
                permission=permission,
                deleted_at__isnull=True,
            ).exists()
        )

    @patch("accounts.service.ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit")
    def test_delegation_permission_donne_un_droit_temporaire(self, _mock_cache):
        source = self.creer_acteur(username="source", email="source@fasoim.local")
        cible = self.creer_acteur(username="cible", email="cible@fasoim.local")
        permission = PermissionService.creer_permission_systeme(
            code="attribuer_role",
            libelle="Attribuer rôle",
            module="accounts",
        )
        affectation_cible = AffectationActeurService.creer_affectation(
            acteur=cible,
            niveau_affectation=AffectationActeur.NiveauAffectation.NATIONAL,
            affecte_par=self.admin,
        )

        delegation = DelegationActeurService.creer_delegation(
            acteur_source=source,
            acteur_cible=cible,
            affectation_acteur=affectation_cible,
            type_delegation=DelegationActeur.TypeDelegation.PERMISSION,
            permission=permission,
            date_fin=timezone.localdate() + timedelta(days=5),
            motif="Remplacement temporaire.",
        )
        resultat = ControleAccesService.acteur_peut(
            cible,
            "attribuer_role",
            affectation=affectation_cible,
        )
        DelegationActeurService.terminer_delegation(delegation)
        refus = ControleAccesService.acteur_peut(
            cible,
            "attribuer_role",
            affectation=affectation_cible,
        )

        self.assertTrue(resultat.autorise)
        self.assertFalse(refus.autorise)
        delegation.refresh_from_db()
        self.assertEqual(delegation.statut, DelegationActeur.Statut.TERMINEE)

    @patch("accounts.service.ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit")
    def test_suppression_logique_acteur_brouille_uniques_et_cascade(self, _mock_cache):
        acteur = self.creer_acteur(username="cascade", email="cascade@fasoim.local")
        role, permission = self.creer_role_permission("desactiver_acteur")
        affectation = AffectationActeurService.creer_affectation(
            acteur=acteur,
            niveau_affectation=AffectationActeur.NiveauAffectation.NATIONAL,
            affecte_par=self.admin,
        )
        attribution_role = AffectationRoleService.attribuer_role(affectation, role, attribue_par=self.admin)
        attribution_permission = AffectationPermissionService.attribuer_permission_directe(
            affectation,
            permission,
            attribue_par=self.admin,
        )
        demande = DemandePermissionService.soumettre_demande(
            acteur=acteur,
            affectation=affectation,
            permission=permission,
            justification="Demande à annuler par cascade.",
        )

        ActeurService.supprimer_logiquement_synchrone(acteur, auteur=self.admin)

        acteur.refresh_from_db()
        affectation.refresh_from_db()
        attribution_role.refresh_from_db()
        attribution_permission.refresh_from_db()
        demande.refresh_from_db()

        self.assertIsNotNone(acteur.deleted_at)
        self.assertFalse(acteur.is_active)
        self.assertNotEqual(acteur.email, "cascade@fasoim.local")
        self.assertIsNotNone(affectation.deleted_at)
        self.assertEqual(affectation.statut, AffectationActeur.Statut.ANNULEE)
        self.assertIsNotNone(attribution_role.deleted_at)
        self.assertEqual(attribution_role.statut, AffectationRole.Statut.RETIRE)
        self.assertIsNotNone(attribution_permission.deleted_at)
        self.assertEqual(attribution_permission.statut, AffectationPermission.Statut.RETIREE)
        self.assertEqual(demande.statut, DemandePermission.Statut.ANNULEE)


class AccountsAPITests(TestCase):
    """Tests des routes principales du module accounts."""

    def setUp(self):
        self.client = APIClient()
        self.admin = Acteur.objects.create_superuser(
            username="adminapi",
            email="adminapi@fasoim.local",
            password="AdminPass123!",
            first_name="Admin",
            last_name="API",
        )
        self.client.force_authenticate(self.admin)

    @patch("accounts.service.ServiceAsynchroneAccounts.envoyer_email_bienvenue_apres_commit")
    def test_api_superuser_cree_acteur_sans_exposer_password(self, mock_email):
        response = self.client.post(
            reverse("accounts:acteur-list"),
            {
                "email": "api.acteur@fasoim.local",
                "first_name": "Api",
                "last_name": "Acteur",
                "telephone": "70000009",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertNotIn("password", response.data)
        acteur = Acteur.objects.get(email="api.acteur@fasoim.local")
        self.assertTrue(acteur.check_password(MOT_DE_PASSE_ACTEUR_PAR_DEFAUT))
        mock_email.assert_called_once_with(acteur.id, MOT_DE_PASSE_ACTEUR_PAR_DEFAUT)

    def test_api_superuser_cree_role_permission_et_liaison(self):
        role_response = self.client.post(
            reverse("accounts:role-list"),
            {
                "libelle": "Responsable test",
                "description": "Rôle créé par test API.",
                "niveau": 30,
                "perimetre_autorise": Role.Perimetre.CENTRE,
            },
            format="json",
        )
        permission_response = self.client.post(
            reverse("accounts:permission-list"),
            {
                "code": "api_permission_test",
                "libelle": "Permission API test",
                "module": "accounts",
                "description": "Permission créée par test API.",
            },
            format="json",
        )

        self.assertEqual(role_response.status_code, status.HTTP_201_CREATED, role_response.data)
        self.assertEqual(permission_response.status_code, status.HTTP_201_CREATED, permission_response.data)

        lien_response = self.client.post(
            reverse("accounts:role-permission-list"),
            {
                "role_id": role_response.data["id"],
                "permission_id": permission_response.data["id"],
                "est_delegable": True,
                "perimetre_delegation_max": Role.Perimetre.CENTRE,
            },
            format="json",
        )

        self.assertEqual(lien_response.status_code, status.HTTP_201_CREATED, lien_response.data)
        self.assertTrue(
            Role.objects.filter(code="ROLE_RESPONSABLE_TEST", deleted_at__isnull=True).exists()
        )
        self.assertTrue(
            Permission.objects.filter(code="api_permission_test", deleted_at__isnull=True).exists()
        )

    @patch("accounts.service.ServiceAsynchroneAccounts.recalculer_cache_permissions_apres_commit")
    def test_api_superuser_cree_affectation_acteur(self, mock_cache):
        acteur = Acteur.objects.create_user(
            username="affecteapi",
            email="affecteapi@fasoim.local",
            password="SecretPass123!",
            first_name="Affecté",
            last_name="API",
        )

        response = self.client.post(
            reverse("accounts:affectation-acteur-list"),
            {
                "acteur_id": acteur.id,
                "niveau_affectation": AffectationActeur.NiveauAffectation.REGION,
                "region_code": "CENTRE",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["region_code"], "CENTRE")
        self.assertTrue(
            AffectationActeur.objects.filter(
                acteur=acteur,
                region_code="CENTRE",
                deleted_at__isnull=True,
            ).exists()
        )
        mock_cache.assert_called_once_with(acteur.id)
