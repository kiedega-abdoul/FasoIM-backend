from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.management.commands.seed_accounts import PERMISSIONS_SYSTEME
from accounts.models import (
    Acteur,
    AffectationActeur,
    AffectationRole,
    Permission,
    Role,
    RolePermission,
)
from affectations.models import CentreImmersion, RegionImmersion
from sessions_app.models import ParametreSession, SessionImmersion

from .detectors.base import Anomalie, Detecteur
from .detectors.registry import detecteurs, get_detecteur
from .models import AlerteIncident
from .repository import AlerteIncidentRepository
from .serializers import AlerteIncidentSerializer, SignalementIncidentSerializer
from .service import (
    AlerteAutomatiqueService,
    AlerteIncidentService,
    ValidationIncidentErreur,
)
from .tasks import ProgressionIncidentsService, scanner_module_task


CACHE_TEST = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "incidents-tests",
    }
}


@override_settings(
    CACHES=CACHE_TEST,
    INCIDENTS_CONTROLES_CIBLES_ACTIFS=False,
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class BaseIncidentTest(TestCase):
    PERMISSIONS_INCIDENTS = [
        "signaler_incident",
        "modifier_incident",
        "prendre_en_charge_incident",
        "mettre_incident_en_attente",
        "resoudre_incident",
        "cloturer_incident",
        "annuler_incident",
        "escalader_incident",
        "consulter_incidents",
        "generer_alerte_automatique",
    ]

    def setUp(self):
        self.client = APIClient()
        self.admin = Acteur.objects.create_superuser(
            username="admin-incidents",
            email="admin.incidents@fasoim.local",
            password="AdminPass123!",
            first_name="Admin",
            last_name="Incidents",
            statut=Acteur.Statut.ACTIF,
        )
        self.region = RegionImmersion.objects.create(
            code="CENTRE",
            nom="Centre",
        )
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="CTR-INC-001",
            nom="Centre test incidents",
            province="Kadiogo",
            ville="Ouagadougou",
        )
        aujourd_hui = timezone.localdate()
        self.session = SessionImmersion.objects.create(
            nom="Session incidents",
            annee=aujourd_hui.year,
            numero_promotion=2,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=aujourd_hui - timedelta(days=1),
            date_fin=aujourd_hui + timedelta(days=30),
            statut=SessionImmersion.Statut.EN_COURS,
            description="Session utilisée pour tester le gardien des incidents.",
        )
        ParametreSession.objects.create(
            session=self.session,
            mode_entree=ParametreSession.ModeEntree.MIXTE,
            visite_medicale_active=True,
            directives_generales="Directives de test.",
            consignes_generales="Consignes de test.",
        )
        self.acteur = self.creer_acteur_autorise("agent-incidents")

    def creer_acteur_autorise(self, username, *, niveau=None, centre=None, codes=None):
        acteur = Acteur.objects.create_user(
            username=username,
            email=f"{username}@fasoim.local",
            password="SecretPass123!",
            first_name="Agent",
            last_name=username,
            statut=Acteur.Statut.ACTIF,
        )
        niveau = niveau or AffectationActeur.NiveauAffectation.CENTRE
        centre = self.centre if centre is None else centre
        role = Role.objects.create(
            code=f"ROLE_{username.upper().replace('-', '_')}",
            libelle=f"Rôle {username}",
            niveau=30,
            perimetre_autorise={
                AffectationActeur.NiveauAffectation.CENTRE: Role.Perimetre.CENTRE,
                AffectationActeur.NiveauAffectation.REGION: Role.Perimetre.REGION,
                AffectationActeur.NiveauAffectation.NATIONAL: Role.Perimetre.NATIONAL,
                AffectationActeur.NiveauAffectation.PLATEFORME: Role.Perimetre.PLATEFORME,
            }[niveau],
            est_systeme=False,
            est_modifiable=True,
        )
        permissions = codes if codes is not None else [
            code
            for code in self.PERMISSIONS_INCIDENTS
            if code != "generer_alerte_automatique"
        ]
        for code in permissions:
            permission, _ = Permission.objects.get_or_create(
                code=code,
                defaults={
                    "libelle": code.replace("_", " ").capitalize(),
                    "module": "incidents",
                    "est_systeme": True,
                },
            )
            RolePermission.objects.create(
                role=role,
                permission=permission,
                est_delegable=True,
                perimetre_delegation_max=role.perimetre_autorise,
            )
        affectation = AffectationActeur.objects.create(
            acteur=acteur,
            session=(self.session if niveau != AffectationActeur.NiveauAffectation.NATIONAL else None),
            niveau_affectation=niveau,
            region_code=self.region.code if niveau in {
                AffectationActeur.NiveauAffectation.REGION,
                AffectationActeur.NiveauAffectation.CENTRE,
            } else "",
            centre_id=centre.id if niveau == AffectationActeur.NiveauAffectation.CENTRE else None,
            statut=AffectationActeur.Statut.ACTIVE,
            affecte_par=self.admin,
        )
        AffectationRole.objects.create(
            affectation_acteur=affectation,
            role=role,
            attribue_par=self.admin,
        )
        return acteur

    def signaler(self, *, acteur=None, gravite=None, concerne=None, raison=None):
        return AlerteIncidentService.signaler_manuellement(
            acteur=acteur or self.acteur,
            niveau_gravite=gravite or AlerteIncident.NiveauGravite.ELEVE,
            concerne=concerne or {
                "type": AlerteIncident.TypeConcerne.CENTRE,
                "id": self.centre.id,
            },
            raison=raison or "Une panne électrique perturbe le fonctionnement du centre.",
        )


class SignalementIncidentTests(BaseIncidentTest):
    def test_serializer_signalement_expose_exactement_trois_champs(self):
        self.assertEqual(
            set(SignalementIncidentSerializer().fields),
            {"niveau_gravite", "concerne", "raison"},
        )

    def test_signalement_prend_le_createur_depuis_acteur_authentifie(self):
        incident = self.signaler()

        self.assertEqual(incident.cree_par, self.acteur)
        self.assertEqual(incident.type, AlerteIncident.Type.INCIDENT)
        self.assertEqual(incident.origine, AlerteIncident.Origine.MANUELLE)
        self.assertEqual(incident.centre, self.centre)
        self.assertEqual(incident.region, self.region)
        self.assertEqual(incident.session, self.session)
        self.assertEqual(incident.statut, AlerteIncident.Statut.NOUVEAU)
        self.assertEqual(
            incident.niveau_confidentialite,
            AlerteIncident.Confidentialite.RESTREINTE,
        )

    def test_gravite_critique_rend_signalement_bloquant(self):
        incident = self.signaler(gravite=AlerteIncident.NiveauGravite.CRITIQUE)
        self.assertTrue(incident.est_bloquante)

    def test_categorie_est_classee_depuis_la_raison(self):
        incident = self.signaler(
            raison="Un immergé a fait un malaise pendant le rassemblement général."
        )
        self.assertEqual(incident.categorie, AlerteIncident.Categorie.SANTE)

    def test_raison_trop_courte_est_refusee(self):
        with self.assertRaises(ValidationIncidentErreur):
            self.signaler(raison="Panne")

    def test_acteur_sans_permission_est_refuse(self):
        acteur = Acteur.objects.create_user(
            username="sans-droit",
            email="sans-droit@fasoim.local",
            password="SecretPass123!",
            statut=Acteur.Statut.ACTIF,
        )
        with self.assertRaises(ValidationIncidentErreur):
            self.signaler(acteur=acteur)

    def test_acteur_hors_perimetre_est_refuse(self):
        autre_region = RegionImmersion.objects.create(code="NORD", nom="Nord")
        autre_centre = CentreImmersion.objects.create(
            region=autre_region,
            code="CTR-NORD-001",
            nom="Centre Nord",
            province="Yatenga",
            ville="Ouahigouya",
        )
        with self.assertRaises(ValidationIncidentErreur):
            self.signaler(
                concerne={
                    "type": AlerteIncident.TypeConcerne.CENTRE,
                    "id": autre_centre.id,
                }
            )

    def test_api_refuse_un_champ_createur_fourni_par_client(self):
        self.client.force_authenticate(self.acteur)
        reponse = self.client.post(
            reverse("incidents:alertes-incidents-list"),
            {
                "niveau_gravite": AlerteIncident.NiveauGravite.ELEVE,
                "concerne": {
                    "type": AlerteIncident.TypeConcerne.CENTRE,
                    "id": self.centre.id,
                },
                "raison": "Une panne électrique perturbe le centre depuis plusieurs minutes.",
                "cree_par": self.admin.id,
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cree_par", reponse.data)

    def test_api_cree_signalement_avec_trois_champs(self):
        self.client.force_authenticate(self.acteur)
        reponse = self.client.post(
            reverse("incidents:alertes-incidents-list"),
            {
                "niveau_gravite": AlerteIncident.NiveauGravite.MOYEN,
                "concerne": {
                    "type": AlerteIncident.TypeConcerne.CENTRE,
                    "id": self.centre.id,
                },
                "raison": "Une fuite d'eau importante est visible dans le dortoir principal.",
            },
            format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        incident = AlerteIncident.objects.get(id=reponse.data["id"])
        self.assertEqual(incident.cree_par, self.acteur)
        self.assertNotIn("modele_source", reponse.data)
        self.assertNotIn("contexte", reponse.data)


class CycleVieIncidentTests(BaseIncidentTest):
    def test_cycle_complet_prise_en_charge_attente_resolution_cloture(self):
        incident = self.signaler()
        incident = AlerteIncidentService.prendre_en_charge(
            incident.id,
            acteur=self.acteur,
            observation="Vérification commencée.",
        )
        self.assertEqual(incident.statut, AlerteIncident.Statut.EN_COURS)
        self.assertIsNotNone(incident.date_prise_en_charge)

        incident = AlerteIncidentService.mettre_en_attente(
            incident.id,
            acteur=self.acteur,
            motif="Attente de la réparation par le technicien.",
        )
        self.assertEqual(incident.statut, AlerteIncident.Statut.EN_ATTENTE)

        incident = AlerteIncidentService.prendre_en_charge(
            incident.id,
            acteur=self.acteur,
        )
        incident = AlerteIncidentService.resoudre(
            incident.id,
            acteur=self.acteur,
            resolution="Le circuit défectueux a été isolé et réparé.",
        )
        self.assertEqual(incident.statut, AlerteIncident.Statut.RESOLU)
        self.assertIsNotNone(incident.date_resolution)

        incident = AlerteIncidentService.cloturer(
            incident.id,
            acteur=self.acteur,
            observation="Contrôle final effectué.",
        )
        self.assertEqual(incident.statut, AlerteIncident.Statut.CLOTURE)
        self.assertIsNotNone(incident.date_cloture)

    def test_cloture_directe_est_refusee(self):
        incident = self.signaler()
        with self.assertRaises(ValidationIncidentErreur):
            AlerteIncidentService.cloturer(incident.id, acteur=self.acteur)

    def test_signalement_automatique_ne_se_modifie_pas_manuellement(self):
        anomalie = Anomalie(
            code="TEST_AUTO",
            cle="TEST_AUTO:1",
            titre="Alerte automatique test",
            description="Une anomalie automatique de test a été détectée.",
            categorie=AlerteIncident.Categorie.SYSTEME,
            module_source="tests",
            modele_source="ObjetTest",
            objet_source_id=1,
        )
        incident, _ = AlerteAutomatiqueService.enregistrer_anomalie(anomalie)
        with self.assertRaises(ValidationIncidentErreur):
            AlerteIncidentService.modifier_signalement(
                incident.id,
                acteur=self.admin,
                raison="Tentative de modification manuelle interdite.",
            )

    def test_escalade_augmente_gravite_et_compteur(self):
        incident = self.signaler(gravite=AlerteIncident.NiveauGravite.MOYEN)
        incident = AlerteIncidentService.escalader(
            incident.id,
            acteur=self.acteur,
            motif="Aucune réponse malgré le premier rappel.",
        )
        self.assertEqual(incident.niveau_gravite, AlerteIncident.NiveauGravite.ELEVE)
        self.assertEqual(incident.niveau_escalade, 1)
        self.assertIsNotNone(incident.date_derniere_escalade)

    def test_suppression_logique_annule_un_incident_ouvert(self):
        incident = self.signaler()
        incident.supprimer_logiquement()
        incident.refresh_from_db()
        self.assertIsNotNone(incident.deleted_at)
        self.assertEqual(incident.statut, AlerteIncident.Statut.ANNULE)


class AlerteAutomatiqueTests(BaseIncidentTest):
    def anomalie(self, **options):
        donnees = {
            "code": "TEST_INTEGRITE",
            "cle": "TEST_INTEGRITE:centre:1",
            "titre": "Anomalie d'intégrité",
            "description": "Une anomalie persistante a été observée dans les données.",
            "categorie": AlerteIncident.Categorie.SYSTEME,
            "gravite": AlerteIncident.NiveauGravite.ELEVE,
            "type_concerne": AlerteIncident.TypeConcerne.CENTRE,
            "session_id": self.session.id,
            "centre_id": self.centre.id,
            "module_source": "tests",
            "modele_source": "ObjetTest",
            "objet_source_id": 1,
            "est_bloquante": True,
        }
        donnees.update(options)
        return Anomalie(**donnees)

    def test_deduplication_actualise_incident_existant(self):
        premier, cree = AlerteAutomatiqueService.enregistrer_anomalie(self.anomalie())
        second, recree = AlerteAutomatiqueService.enregistrer_anomalie(
            self.anomalie(description="La même anomalie est toujours présente.")
        )
        self.assertTrue(cree)
        self.assertFalse(recree)
        self.assertEqual(premier.id, second.id)
        self.assertEqual(second.nombre_occurrences, 2)
        self.assertEqual(AlerteIncident.objects.filter(cle_deduplication=self.anomalie().cle).count(), 1)

    def test_anomalie_absente_est_resolue_automatiquement(self):
        incident, _ = AlerteAutomatiqueService.enregistrer_anomalie(self.anomalie())
        AlerteIncident.objects.filter(id=incident.id).update(
            date_derniere_detection=timezone.now() - timedelta(minutes=10)
        )
        total = AlerteAutomatiqueService.resoudre_absentes(
            module="tests",
            codes=("TEST_INTEGRITE",),
            debut_scan=timezone.now() - timedelta(minutes=1),
        )
        incident.refresh_from_db()
        self.assertEqual(total, 1)
        self.assertEqual(incident.statut, AlerteIncident.Statut.RESOLU)

    def test_anomalie_non_resoluble_reste_ouverte(self):
        incident, _ = AlerteAutomatiqueService.enregistrer_anomalie(
            self.anomalie(resolution_automatique=False)
        )
        AlerteIncident.objects.filter(id=incident.id).update(
            date_derniere_detection=timezone.now() - timedelta(minutes=10)
        )
        total = AlerteAutomatiqueService.resoudre_absentes(
            module="tests",
            codes=("TEST_INTEGRITE",),
            debut_scan=timezone.now() - timedelta(minutes=1),
        )
        incident.refresh_from_db()
        self.assertEqual(total, 0)
        self.assertEqual(incident.statut, AlerteIncident.Statut.NOUVEAU)

    def test_detecteur_ne_duplique_pas_les_validations_metier(self):
        # Le détecteur fournit seulement des anomalies déjà observées. Le service
        # incidents ne modifie aucun objet du module propriétaire.
        detecteur = Detecteur("tests", ("TEST_INTEGRITE",), lambda: [self.anomalie()])
        resultat = AlerteAutomatiqueService.executer_detecteur(detecteur)
        self.assertEqual(resultat.detectes, 1)
        self.assertEqual(resultat.crees, 1)
        self.assertEqual(resultat.echecs, 0)


    @override_settings(
        INCIDENTS_TAILLE_LOT_SCAN=50,
        INCIDENTS_MAX_ALERTES_CREEES_PAR_REGLE=1000,
    )
    def test_detecteur_parcourt_plus_de_cinq_cents_anomalies(self):
        def generer():
            for numero in range(1, 502):
                yield Anomalie(
                    code="TEST_VOLUME",
                    cle=f"TEST_VOLUME:{numero}",
                    titre=f"Anomalie {numero}",
                    description="Anomalie de volume détectée.",
                    categorie=AlerteIncident.Categorie.SYSTEME,
                    module_source="tests-volume",
                    modele_source="Test",
                    objet_source_id=numero,
                )

        detecteur = Detecteur("tests-volume", ("TEST_VOLUME",), generer)
        resultat = AlerteAutomatiqueService.executer_detecteur(detecteur)

        self.assertEqual(resultat.detectes, 501)
        self.assertEqual(resultat.crees, 501)
        self.assertTrue(
            AlerteIncident.objects.filter(
                cle_deduplication="TEST_VOLUME:501",
                statut=AlerteIncident.Statut.NOUVEAU,
            ).exists()
        )

    @override_settings(
        INCIDENTS_TAILLE_LOT_SCAN=2,
        INCIDENTS_MAX_ALERTES_CREEES_PAR_REGLE=2,
    )
    def test_limite_concerne_les_creations_pas_les_objets_controles(self):
        def generer():
            for numero in range(1, 5):
                yield Anomalie(
                    code="TEST_LIMITE_CREATION",
                    cle=f"TEST_LIMITE_CREATION:{numero}",
                    titre=f"Anomalie {numero}",
                    description="Anomalie contrôlée malgré la limite de création.",
                    categorie=AlerteIncident.Categorie.SYSTEME,
                    module_source="tests-limite",
                )

        detecteur = Detecteur(
            "tests-limite",
            ("TEST_LIMITE_CREATION",),
            generer,
        )
        premier = AlerteAutomatiqueService.executer_detecteur(detecteur)
        second = AlerteAutomatiqueService.executer_detecteur(detecteur)

        self.assertEqual(premier.detectes, 4)
        self.assertEqual(premier.crees, 2)
        self.assertEqual(premier.non_crees_limite, 2)
        self.assertEqual(second.detectes, 4)
        self.assertEqual(AlerteIncident.objects.filter(module_source="tests-limite").count(), 4)
        self.assertFalse(
            AlerteIncident.objects.filter(
                module_source="tests-limite",
                statut=AlerteIncident.Statut.RESOLU,
            ).exists()
        )


class PerimetreEtConfidentialiteTests(BaseIncidentTest):
    def test_acteur_centre_ne_voit_pas_incident_autre_centre(self):
        autre_region = RegionImmersion.objects.create(code="EST", nom="Est")
        autre_centre = CentreImmersion.objects.create(
            region=autre_region,
            code="CTR-EST-001",
            nom="Centre Est",
            province="Gourma",
            ville="Fada N'Gourma",
        )
        visible = self.signaler()
        cache = AlerteIncident.objects.create(
            session=self.session,
            centre=autre_centre,
            type=AlerteIncident.Type.ALERTE,
            origine=AlerteIncident.Origine.AUTOMATIQUE,
            type_concerne=AlerteIncident.TypeConcerne.CENTRE,
            categorie=AlerteIncident.Categorie.SYSTEME,
            titre="Incident hors périmètre",
            description="Anomalie dans un autre centre.",
            code_detection="TEST_AUTRE_CENTRE",
            module_source="tests",
            cle_deduplication="TEST_AUTRE_CENTRE:1",
        )
        ids = set(AlerteIncidentRepository.visibles_pour(self.acteur).values_list("id", flat=True))
        self.assertIn(visible.id, ids)
        self.assertNotIn(cache.id, ids)

    def test_affectation_nationale_sans_session_voit_tous_incidents(self):
        national = self.creer_acteur_autorise(
            "national-incidents",
            niveau=AffectationActeur.NiveauAffectation.NATIONAL,
        )
        incident = self.signaler()
        self.assertTrue(AlerteIncidentRepository.visibles_pour(national).filter(id=incident.id).exists())

    def test_statistiques_acceptent_queryset_deja_limite(self):
        self.signaler()
        autre = AlerteIncident.objects.create(
            session=self.session,
            centre=self.centre,
            type=AlerteIncident.Type.ALERTE,
            origine=AlerteIncident.Origine.AUTOMATIQUE,
            type_concerne=AlerteIncident.TypeConcerne.CENTRE,
            categorie=AlerteIncident.Categorie.SYSTEME,
            titre="Autre incident",
            description="Autre anomalie.",
            code_detection="AUTRE",
            module_source="tests",
            cle_deduplication="AUTRE:1",
        )
        donnees = AlerteIncidentRepository.statistiques(
            queryset=AlerteIncident.objects.filter(id=autre.id)
        )
        self.assertEqual(donnees["total"], 1)

    def test_createur_peut_relire_sa_raison_de_sante(self):
        incident = self.signaler(
            raison="Un immergé a fait un malaise pendant le rassemblement du matin."
        )
        requete = type("Request", (), {"user": self.acteur})()
        donnees = AlerteIncidentSerializer(incident, context={"request": requete}).data
        self.assertEqual(donnees["description"], incident.description)

    def test_autre_acteur_sans_droit_medical_recoit_description_masquee(self):
        incident = self.signaler(
            raison="Un immergé a fait un malaise et présente une douleur importante."
        )
        autre = self.creer_acteur_autorise(
            "autre-agent",
            codes=["consulter_incidents"],
        )
        requete = type("Request", (), {"user": autre})()
        donnees = AlerteIncidentSerializer(incident, context={"request": requete}).data
        self.assertNotEqual(donnees["description"], incident.description)
        self.assertIn("Détails réservés", donnees["description"])


    def test_acteur_regional_voit_alerte_regionale_sans_centre(self):
        regional = self.creer_acteur_autorise(
            "directeur-regional-test",
            niveau=AffectationActeur.NiveauAffectation.REGION,
            codes=["consulter_incidents"],
        )
        alerte = AlerteIncident.objects.create(
            session=self.session,
            region=self.region,
            type=AlerteIncident.Type.ALERTE,
            origine=AlerteIncident.Origine.AUTOMATIQUE,
            type_concerne=AlerteIncident.TypeConcerne.DONNEE,
            categorie=AlerteIncident.Categorie.SECURITE_ACCES,
            titre="Poste régional vacant",
            description="Aucun directeur régional actif.",
            code_detection="TEST_REGION",
            module_source="tests",
            cle_deduplication="TEST_REGION:CENTRE",
        )
        self.assertTrue(
            AlerteIncidentRepository.visibles_pour(regional)
            .filter(id=alerte.id)
            .exists()
        )

    def test_raison_manuelle_sensible_sans_mot_cle_reste_masquee(self):
        incident = self.signaler(
            raison="L'immergé a vomi et a perdu connaissance soudainement."
        )
        self.assertEqual(incident.categorie, AlerteIncident.Categorie.AUTRE)
        self.assertEqual(
            incident.niveau_confidentialite,
            AlerteIncident.Confidentialite.RESTREINTE,
        )
        autre = self.creer_acteur_autorise(
            "lecteur-restreint",
            codes=["consulter_incidents"],
        )
        requete = type("Request", (), {"user": autre})()
        donnees = AlerteIncidentSerializer(incident, context={"request": requete}).data
        self.assertNotEqual(donnees["description"], incident.description)
        self.assertIn("Détails réservés", donnees["description"])

    def test_liste_incidents_est_paginee_et_url_non_redondante(self):
        for numero in range(30):
            AlerteIncident.objects.create(
                session=self.session,
                region=self.region,
                centre=self.centre,
                type=AlerteIncident.Type.ALERTE,
                origine=AlerteIncident.Origine.AUTOMATIQUE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                categorie=AlerteIncident.Categorie.SYSTEME,
                titre=f"Alerte pagination {numero}",
                description="Alerte créée pour tester la pagination.",
                code_detection="TEST_PAGINATION",
                module_source="tests",
                cle_deduplication=f"TEST_PAGINATION:{numero}",
            )
        self.client.force_authenticate(self.acteur)
        url = reverse("incidents:alertes-incidents-list")
        reponse = self.client.get(url)

        self.assertEqual(url, "/api/incidents/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertEqual(reponse.data["count"], 30)
        self.assertEqual(len(reponse.data["results"]), 25)


class DetecteursEtTachesTests(BaseIncidentTest):
    def test_registre_contient_toutes_les_applications_implantees(self):
        self.assertEqual(
            {detecteur.module for detecteur in detecteurs()},
            {
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
            },
        )

    def test_tous_les_detecteurs_s_executent_sans_erreur(self):
        for detecteur in detecteurs():
            with self.subTest(module=detecteur.module):
                list(detecteur.fonction())

    def test_accounts_detecte_permission_systeme_absente(self):
        permission_attendue = PERMISSIONS_SYSTEME[0].code
        Permission.objects.filter(code=permission_attendue).delete()
        anomalies = list(get_detecteur("accounts").fonction())
        self.assertTrue(
            any(
                anomalie.code == "ACC_PERMISSION_SYSTEME_ABSENTE"
                and anomalie.contexte.get("permission_code") == permission_attendue
                for anomalie in anomalies
            )
        )

    def test_accounts_detecte_permission_systeme_alteree(self):
        definition = PERMISSIONS_SYSTEME[0]
        Permission.objects.update_or_create(
            code=definition.code,
            defaults={
                "libelle": definition.libelle,
                "module": definition.module,
                "est_systeme": False,
                "statut": Permission.Statut.INACTIVE,
            },
        )
        anomalies = list(get_detecteur("accounts").fonction())
        self.assertTrue(
            any(
                anomalie.code == "ACC_PERMISSION_SYSTEME_ALTEREE"
                and anomalie.contexte.get("permission_code") == definition.code
                for anomalie in anomalies
            )
        )

    def test_tache_module_inconnu_retourne_echec(self):
        resultat = scanner_module_task.apply(kwargs={"module": "inconnu"}).get()
        self.assertEqual(resultat["statut"], ProgressionIncidentsService.ECHEC)
        self.assertIn("inconnu", resultat["erreur"])

    def test_configuration_beat_prevoit_scan_toutes_les_cinq_minutes(self):
        configuration = settings.CELERY_BEAT_SCHEDULE[
            "incidents-scan-integrite-toutes-les-5-minutes"
        ]
        self.assertEqual(configuration["task"], "incidents.scanner_integrite_global")
        self.assertEqual(str(configuration["schedule"]), "<crontab: */5 * * * * (m/h/dM/MY/d)>" )

    @patch("incidents.tasks.AlerteAutomatiqueService.executer_detecteur")
    def test_tache_module_appelle_un_seul_detecteur(self, executer):
        resultat_scan = type("Resultat", (), {"en_dict": lambda self: {"module": "repas"}})()
        executer.return_value = resultat_scan
        resultat = scanner_module_task.apply(kwargs={"module": "repas"}).get()
        self.assertEqual(resultat["statut"], ProgressionIncidentsService.TERMINEE)
        executer.assert_called_once()

    def test_verrou_scan_depasse_la_limite_celery(self):
        self.assertGreater(
            ProgressionIncidentsService.EXPIRATION_VERROU,
            settings.CELERY_TASK_TIME_LIMIT,
        )

    def test_seed_attribue_les_permissions_incidents_et_retire_creer_alerte(self):
        call_command("seed_accounts", verbosity=0)
        self.assertFalse(
            Permission.objects.filter(
                code="creer_alerte",
                deleted_at__isnull=True,
            ).exists()
        )
        administrateur = Role.objects.get(code="ADMINISTRATEUR")
        self.assertTrue(
            RolePermission.objects.filter(
                role=administrateur,
                permission__code="generer_alerte_automatique",
                statut=RolePermission.Statut.ACTIVE,
                deleted_at__isnull=True,
            ).exists()
        )
