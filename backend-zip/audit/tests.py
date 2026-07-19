from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import (
    Acteur,
    AffectationActeur,
    AffectationRole,
    Permission,
    Role,
    RolePermission,
)
from affectations.models import CentreImmersion, RegionImmersion
from immerges.models import Immerge
from sessions_app.models import SessionImmersion

from .models import JournalAction
from .repository import JournalActionRepository
from .service import JournalActionService
from .tasks import cle_progression, generer_export_audit_task


CACHE_TEST = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "audit-tests",
    }
}


@override_settings(
    CACHES=CACHE_TEST,
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class AuditBaseTest(TestCase):
    PERMISSIONS = {
        "consulter_journaux_audit",
        "consulter_statistiques_audit",
        "consulter_audit_securite",
        "consulter_audit_acces_publics",
        "exporter_journaux_audit",
        "consulter_activite_acteur",
        "consulter_activite_immerge",
    }

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = Acteur.objects.create_superuser(
            username="admin-audit",
            email="admin.audit@fasoim.local",
            password="AdminPass123!",
            first_name="Admin",
            last_name="Audit",
            statut=Acteur.Statut.ACTIF,
        )
        aujourd_hui = timezone.localdate()
        self.session = SessionImmersion.objects.create(
            nom="Session audit",
            annee=aujourd_hui.year,
            numero_promotion=8,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=aujourd_hui - timedelta(days=2),
            date_fin=aujourd_hui + timedelta(days=20),
            statut=SessionImmersion.Statut.EN_COURS,
        )
        self.region = RegionImmersion.objects.create(code="CENTRE_AUDIT", nom="Centre Audit")
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="AUDIT-CTR-01",
            nom="Centre audit",
            province="Kadiogo",
            ville="Ouagadougou",
        )
        self.immerge = Immerge.objects.create(
            session=self.session,
            type_immerge=Immerge.TypeImmerge.BEPC,
            origine_id=1,
            code_fasoim="IP-AUDIT-00001",
            statut=Immerge.Statut.AFFECTE_CENTRE,
        )
        self.acteur = self.creer_acteur_autorise(
            "dgas-audit",
            niveau=AffectationActeur.NiveauAffectation.NATIONAL,
        )

    def creer_acteur_autorise(self, username, *, niveau, region=None, centre=None, permissions=None):
        acteur = Acteur.objects.create_user(
            username=username,
            email=f"{username}@fasoim.local",
            password="SecretPass123!",
            first_name="Agent",
            last_name=username,
            statut=Acteur.Statut.ACTIF,
        )
        perimetres = {
            AffectationActeur.NiveauAffectation.PLATEFORME: Role.Perimetre.PLATEFORME,
            AffectationActeur.NiveauAffectation.NATIONAL: Role.Perimetre.NATIONAL,
            AffectationActeur.NiveauAffectation.REGION: Role.Perimetre.REGION,
            AffectationActeur.NiveauAffectation.CENTRE: Role.Perimetre.CENTRE,
        }
        role = Role.objects.create(
            code=f"ROLE_{username.upper().replace('-', '_')}",
            libelle=f"Rôle {username}",
            niveau=10,
            perimetre_autorise=perimetres[niveau],
            est_systeme=False,
            est_modifiable=True,
        )
        for code in permissions or self.PERMISSIONS:
            permission, _ = Permission.objects.get_or_create(
                code=code,
                defaults={"libelle": code, "module": "audit", "est_systeme": True},
            )
            RolePermission.objects.create(
                role=role,
                permission=permission,
                perimetre_delegation_max=role.perimetre_autorise,
            )
        affectation = AffectationActeur.objects.create(
            acteur=acteur,
            session=None,
            niveau_affectation=niveau,
            region_code=(region or self.region).code
            if niveau in {AffectationActeur.NiveauAffectation.REGION, AffectationActeur.NiveauAffectation.CENTRE}
            else "",
            centre_id=(centre or self.centre).id
            if niveau == AffectationActeur.NiveauAffectation.CENTRE
            else None,
            affecte_par=self.admin,
        )
        AffectationRole.objects.create(
            affectation_acteur=affectation,
            role=role,
            attribue_par=self.admin,
        )
        return acteur

    def creer_journal(self, **kwargs):
        donnees = {
            "code_action": "valider_affectation_centre",
            "module_source": "affectations",
            "resultat": JournalAction.Resultat.SUCCES,
            "acteur": self.acteur,
            "session": self.session,
            "region": self.region,
            "centre": self.centre,
            "objet_type": "AffectationCentre",
            "objet_id": 15,
            "motif": "Validation réussie.",
        }
        donnees.update(kwargs)
        return JournalActionService.journaliser(**donnees)


class JournalActionServiceTests(AuditBaseTest):
    def test_service_cree_un_journal_contextualise(self):
        journal = self.creer_journal(contexte={"avant": "PROPOSEE", "apres": "ACTIVE"})

        self.assertEqual(journal.acteur, self.acteur)
        self.assertEqual(journal.session, self.session)
        self.assertEqual(journal.region, self.region)
        self.assertEqual(journal.centre, self.centre)
        self.assertEqual(journal.resultat, JournalAction.Resultat.SUCCES)
        self.assertEqual(journal.contexte["apres"], "ACTIVE")

    def test_donnees_sensibles_sont_masquees(self):
        journal = self.creer_journal(
            contexte={
                "password": "Secret123!",
                "access": "jwt-secret",
                "observation_medicale": "Diagnostic confidentiel",
                "normal": "visible",
            }
        )

        self.assertEqual(journal.contexte["password"], "[MASQUE]")
        self.assertEqual(journal.contexte["access"], "[MASQUE]")
        self.assertEqual(journal.contexte["observation_medicale"], "[MASQUE]")
        self.assertEqual(journal.contexte["normal"], "visible")

    def test_journal_est_immuable_et_non_supprimable(self):
        journal = self.creer_journal()
        journal.motif = "Modification interdite"

        with self.assertRaises(ValidationError):
            journal.save()
        with self.assertRaises(ValidationError):
            journal.delete()

    def test_consultation_publique_immerge_est_journalisee_sans_identifiant_clair(self):
        journal = JournalActionService.journaliser_consultation_immerge(
            immerge=self.immerge,
            session=self.session,
            region=self.region,
            centre=self.centre,
            identifiant_saisi="PV-2026-123456",
            informations_consultees=["affectation", "kits", "consignes"],
        )

        self.assertEqual(journal.origine, JournalAction.Origine.IMMERGE)
        self.assertEqual(journal.immerge, self.immerge)
        self.assertNotIn("PV-2026-123456", str(journal.contexte))
        self.assertTrue(journal.contexte["empreinte_identifiant"])
        self.assertEqual(journal.contexte["identifiant_masque"], "***3456")

    def test_recherche_publique_echouee_ne_lie_aucun_immerge(self):
        journal = JournalActionService.journaliser_consultation_immerge(
            resultat=JournalAction.Resultat.REFUS,
            identifiant_saisi="PV-INVALIDE",
            motif="Identifiant invalide.",
        )

        self.assertIsNone(journal.immerge_id)
        self.assertEqual(journal.origine, JournalAction.Origine.API_PUBLIQUE)
        self.assertEqual(journal.resultat, JournalAction.Resultat.REFUS)

    def test_telechargement_attestation_est_prepare_pour_documents(self):
        attestation = SimpleNamespace(
            pk=8754,
            session=self.session,
            region=self.region,
            centre=self.centre,
            numero="ATT-2026-008754",
        )
        journal = JournalActionService.journaliser_telechargement_attestation(
            immerge=self.immerge,
            attestation=attestation,
            resultat=JournalAction.Resultat.SUCCES,
            contexte={"version": 1, "empreinte_document": "sha256:test"},
        )

        self.assertEqual(journal.code_action, "telecharger_attestation")
        self.assertEqual(journal.objet_type, "SimpleNamespace")
        self.assertEqual(journal.objet_id, 8754)
        self.assertEqual(journal.immerge, self.immerge)

    def test_information_relais_etablissement_est_journalisee(self):
        journal = JournalActionService.journaliser_information_immerge(
            code_action="informer_relais_etablissement",
            resultat=JournalAction.Resultat.SUCCES,
            session=self.session,
            region=self.region,
            canal=JournalAction.Canal.EMAIL,
            contexte={
                "etablissement": "Lycée test",
                "nombre_immerges_concernes": 148,
                "type_relais": "ELEVE_DU_MEME_ETABLISSE",
            },
        )

        self.assertEqual(journal.module_source, "notifications")
        self.assertEqual(journal.contexte["nombre_immerges_concernes"], 148)


class JournalActionAPITests(AuditBaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.acteur)
        self.journal = self.creer_journal()

    def test_liste_et_detail_sont_accessibles(self):
        liste = self.client.get(reverse("audit:journaux-audit-list"))
        detail = self.client.get(reverse("audit:journaux-audit-detail", args=[self.journal.id]))

        self.assertEqual(liste.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(liste.data["count"], 1)
        self.assertEqual(detail.data["id"], self.journal.id)

    def test_creation_modification_suppression_api_sont_interdites(self):
        liste_url = reverse("audit:journaux-audit-list")
        detail_url = reverse("audit:journaux-audit-detail", args=[self.journal.id])

        self.assertIn(
            self.client.post(liste_url, {}).status_code,
            {status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED},
        )
        self.assertIn(
            self.client.patch(detail_url, {"motif": "x"}).status_code,
            {status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED},
        )
        self.assertIn(
            self.client.delete(detail_url).status_code,
            {status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED},
        )

    def test_statistiques_generales_immerges_documents_et_systeme(self):
        JournalActionService.journaliser_consultation_immerge(
            immerge=self.immerge,
            session=self.session,
            region=self.region,
            centre=self.centre,
        )
        JournalActionService.journaliser(
            code_action="telecharger_attestation",
            module_source="documents",
            resultat=JournalAction.Resultat.SUCCES,
            origine=JournalAction.Origine.IMMERGE,
            immerge=self.immerge,
            session=self.session,
            region=self.region,
            centre=self.centre,
        )
        JournalActionService.journaliser(
            code_action="scanner_integrite_global",
            module_source="incidents",
            resultat=JournalAction.Resultat.SUCCES,
            origine=JournalAction.Origine.CELERY,
            task_id="task-test",
            duree_ms=120,
        )

        urls = [
            reverse("audit:journaux-audit-statistiques"),
            reverse("audit:journaux-audit-statistiques-immerges"),
            reverse("audit:journaux-audit-statistiques-documents"),
            reverse("audit:journaux-audit-statistiques-systeme"),
        ]
        reponses = [self.client.get(url) for url in urls]

        self.assertTrue(all(r.status_code == status.HTTP_200_OK for r in reponses))
        self.assertGreaterEqual(reponses[0].data["synthese"]["total"], 4)
        self.assertGreaterEqual(reponses[1].data["consultations"]["reussies"], 1)
        self.assertGreaterEqual(reponses[2].data["attestations"]["immerges_ayant_telecharge"], 1)
        self.assertGreaterEqual(reponses[3].data["synthese"]["succes"], 1)

    def test_perimetre_regional_masque_une_autre_region(self):
        autre_region = RegionImmersion.objects.create(code="AUTRE_AUDIT", nom="Autre Audit")
        autre_centre = CentreImmersion.objects.create(
            region=autre_region,
            code="AUDIT-CTR-02",
            nom="Autre centre audit",
            province="Houet",
            ville="Bobo-Dioulasso",
        )
        acteur_region = self.creer_acteur_autorise(
            "dr-audit",
            niveau=AffectationActeur.NiveauAffectation.REGION,
            region=self.region,
        )
        visible = self.creer_journal(code_action="visible_region")
        self.creer_journal(
            code_action="cache_autre_region",
            region=autre_region,
            centre=autre_centre,
        )
        self.client.force_authenticate(acteur_region)

        reponse = self.client.get(reverse("audit:journaux-audit-list"))
        codes = {ligne["code_action"] for ligne in reponse.data["results"]}

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertIn(visible.code_action, codes)
        self.assertNotIn("cache_autre_region", codes)

    def test_middleware_journalise_automatiquement_une_requete_api(self):
        avant = JournalAction.objects.count()

        reponse = self.client.get(reverse("audit:journaux-audit-list"))

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(JournalAction.objects.count(), avant + 1)
        auto = JournalAction.objects.order_by("-id").first()
        self.assertEqual(auto.acteur_id, self.acteur.id)
        self.assertEqual(auto.module_source, "audit")
        self.assertTrue(auto.code_action.startswith("api_get_"))

    def test_acces_publics_et_activites_sont_consultables_en_lecture_seule(self):
        public = JournalActionService.journaliser_consultation_immerge(
            immerge=self.immerge,
            session=self.session,
            region=self.region,
            centre=self.centre,
        )
        interne = self.creer_journal(code_action="action_interne")

        acces = self.client.get(reverse("audit:journaux-audit-acces-publics"))
        activite_acteur = self.client.get(
            reverse("audit:journaux-audit-activite-acteur", args=[self.acteur.id])
        )
        activite_immerge = self.client.get(
            reverse("audit:journaux-audit-activite-immerge", args=[self.immerge.id])
        )

        self.assertEqual(acces.status_code, status.HTTP_200_OK)
        self.assertEqual(activite_acteur.status_code, status.HTTP_200_OK)
        self.assertEqual(activite_immerge.status_code, status.HTTP_200_OK)
        self.assertIn(public.id, {ligne["id"] for ligne in acces.data["results"]})
        self.assertNotIn(interne.id, {ligne["id"] for ligne in acces.data["results"]})
        self.assertIn(interne.id, {ligne["id"] for ligne in activite_acteur.data["results"]})
        self.assertIn(public.id, {ligne["id"] for ligne in activite_immerge.data["results"]})

    def test_detail_technique_est_masque_sans_permission_securite(self):
        acteur = self.creer_acteur_autorise(
            "auditeur-sans-securite",
            niveau=AffectationActeur.NiveauAffectation.NATIONAL,
            permissions={"consulter_journaux_audit"},
        )
        journal = self.creer_journal()
        JournalAction.objects.filter(id=journal.id).update(
            adresse_ip="127.0.0.1",
            user_agent="AgentSecret",
            chemin_api="/api/secret/",
            task_id="task-secret",
        )
        self.client.force_authenticate(acteur)

        reponse = self.client.get(reverse("audit:journaux-audit-detail", args=[journal.id]))

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertNotIn("adresse_ip", reponse.data)
        self.assertNotIn("user_agent", reponse.data)
        self.assertNotIn("chemin_api", reponse.data)
        self.assertNotIn("task_id", reponse.data)


class AuditExportEtSeedTests(AuditBaseTest):
    def test_export_csv_est_genere_et_journalise(self):
        self.creer_journal()
        with TemporaryDirectory() as dossier:
            with override_settings(MEDIA_ROOT=dossier):
                resultat = generer_export_audit_task.apply(
                    kwargs={
                        "acteur_id": self.acteur.id,
                        "filtres": {"module": "affectations"},
                        "format_export": "CSV",
                    }
                ).get()

                self.assertEqual(resultat["statut"], "TERMINE")
                self.assertTrue(Path(resultat["chemin"]).is_file())
                self.assertGreaterEqual(resultat["total_lignes"], 1)
                self.assertTrue(
                    JournalAction.objects.filter(
                        code_action="exporter_journaux_audit",
                        resultat=JournalAction.Resultat.SUCCES,
                    ).exists()
                )

    def test_seed_cree_permissions_et_associations_audit(self):
        call_command("seed_accounts", verbosity=0)

        self.assertEqual(
            Permission.objects.filter(
                module="audit",
                statut=Permission.Statut.ACTIVE,
                deleted_at__isnull=True,
            ).count(),
            7,
        )
        self.assertGreaterEqual(
            RolePermission.objects.filter(
                permission__module="audit",
                deleted_at__isnull=True,
            ).count(),
            25,
        )

    def test_repository_produit_statistiques_sans_dupliquer_les_donnees(self):
        self.creer_journal()
        JournalActionService.journaliser_consultation_immerge(
            immerge=self.immerge,
            session=self.session,
            region=self.region,
            centre=self.centre,
        )
        queryset = JournalActionRepository.visibles_par_acteur(self.acteur)

        statistiques = JournalActionRepository.statistiques_generales(queryset)

        self.assertGreaterEqual(statistiques["synthese"]["total"], 2)
        self.assertGreaterEqual(statistiques["synthese"]["immerges_distincts"], 1)
