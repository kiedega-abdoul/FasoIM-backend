from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.management.commands.seed_accounts import PERMISSIONS_SYSTEME
from accounts.models import Acteur
from affectations.models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)
from immerges.models import Immerge
from sante.models import RestrictionMedicale, VisiteMedicale
from sante.service import ImpactMedicalService
from sessions_app.models import ParametreSession, SessionImmersion

from .models import (
    DemandeRavitaillementCentre,
    LigneBesoinDenree,
    RepasJournalier,
    SuiviRepas,
)
from .repository import LigneBesoinDenreeRepository, RepasJournalierRepository
from .serializers import RepasCreateSerializer, ServiceMedicalSerializer
from .service import RavitaillementService, RepasService, ValidationRepasErreur
from .tasks import ProgressionRepasService, preparer_suivis_repas_task


CACHE_TEST = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "tests-repas",
    }
}


class RepasFixtureMixin:
    mot_de_passe = "Test-Repas-2026!"

    def creer_socle(self, *, repas_active=True, visite_medicale_active=True):
        self.agent = Acteur.objects.create_user(
            username="responsable-repas-tests",
            email="responsable-repas-tests@fasoim.test",
            password=self.mot_de_passe,
            first_name="Responsable",
            last_name="Repas",
        )
        self.agent.is_superuser = True
        self.agent.is_staff = True
        self.agent.save(update_fields=["is_superuser", "is_staff"])
        self.date_repas = timezone.localdate() + timedelta(days=15)
        self.session = SessionImmersion.objects.create(
            nom="Session repas 2026",
            annee=2026,
            numero_promotion=2,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=timezone.localdate() + timedelta(days=10),
            date_fin=timezone.localdate() + timedelta(days=40),
            statut=SessionImmersion.Statut.EN_PREPARATION,
        )
        ParametreSession.objects.create(
            session=self.session,
            visite_medicale_active=visite_medicale_active,
            hebergement_active=True,
            repas_active=repas_active,
            activites_active=True,
            evaluation_active=True,
        )
        self.region = RegionImmersion.objects.create(
            code="REG-REPAS", nom="Région repas"
        )
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="CTR-REPAS-001",
            nom="Centre repas",
            province="Kadiogo",
            ville="Ouagadougou",
            genre=CentreImmersion.Genre.MIXTE,
            publics_acceptes=[],
            niveaux_acceptes=[],
        )

    def creer_affectation(self, numero):
        immerge = Immerge.objects.create(
            session=self.session,
            type_immerge=Immerge.TypeImmerge.SELECTIONNE,
            origine_id=90_000 + numero,
            code_fasoim=f"IP2026REP{numero:05d}",
            statut=Immerge.Statut.AFFECTE_CENTRE,
        )
        regionale = AffectationRegionale.objects.create(
            immerge=immerge,
            session=self.session,
            region=self.region,
            statut=AffectationRegionale.Statut.ACTIVE,
            affecte_par=self.agent,
        )
        return AffectationCentre.objects.create(
            immerge=immerge,
            session=self.session,
            affectation_regionale=regionale,
            centre=self.centre,
            statut=AffectationCentre.Statut.ACTIVE,
            affecte_par=self.agent,
        )

    def creer_restriction_repas(self, affectation, *, libelle="Sans arachide"):
        visite = VisiteMedicale.objects.create(
            affectation_centre=affectation,
            resultat=VisiteMedicale.Resultat.APTE_SOUS_RESERVE,
            agent_sante=self.agent,
        )
        visite.valider(agent_sante=self.agent)
        return RestrictionMedicale.objects.create(
            visite_medicale=visite,
            libelle=libelle,
            type_restriction=RestrictionMedicale.TypeRestriction.ADAPTATION,
            modules_concernes=[RestrictionMedicale.ModuleConcerne.REPAS],
            description_medicale="Allergie confidentielle à ne pas exposer.",
            consigne_operationnelle="Préparer un repas sans arachide.",
            date_debut=self.session.date_debut,
            date_fin=self.session.date_fin,
            saisie_par=self.agent,
        )

    def creer_demande_validee(self):
        demande = RavitaillementService.creer_demande(
            acteur=self.agent,
            session_id=self.session.id,
            centre_id=self.centre.id,
        )
        RavitaillementService.ajouter_denree(
            demande.id,
            acteur=self.agent,
            code_denree="RIZ",
            designation="Riz",
            conditionnement="SAC",
            contenance_conditionnement=Decimal("50"),
            unite_base="KG",
            quantite_demandee=Decimal("10"),
        )
        RavitaillementService.soumettre(demande.id, acteur=self.agent)
        return RavitaillementService.valider(demande.id, acteur=self.agent)

    def creer_repas(self, *, preparations=None):
        return RepasService.creer(
            acteur=self.agent,
            demande_ravitaillement_id=self.demande.id,
            date_repas=self.date_repas,
            type_repas=RepasJournalier.TypeRepas.DEJEUNER,
            menu_prevu="Riz gras avec viande",
            denrees_prevues=[{"code": "RIZ", "quantite": 2}],
            preparations_speciales_prevues=preparations or {},
        )


class ModelesRepasTests(RepasFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.affectation = self.creer_affectation(1)

    def test_une_seule_demande_active_par_session_et_centre(self):
        DemandeRavitaillementCentre.objects.create(
            session=self.session, centre=self.centre
        )
        with self.assertRaises((ValidationError, IntegrityError)):
            DemandeRavitaillementCentre.objects.create(
                session=self.session, centre=self.centre
            )

    def test_quantite_denree_doit_etre_positive(self):
        demande = DemandeRavitaillementCentre.objects.create(
            session=self.session, centre=self.centre
        )
        with self.assertRaises(ValidationError):
            LigneBesoinDenree.objects.create(
                demande_ravitaillement=demande,
                code_denree="RIZ",
                designation="Riz",
                conditionnement="SAC",
                unite_base="KG",
                quantite_demandee=0,
            )

    def test_suivi_comptage_refuse_nombre_superieur_effectif(self):
        self.demande = self.creer_demande_validee()
        repas = self.creer_repas()
        with self.assertRaises(ValidationError):
            SuiviRepas.objects.create(
                repas_journalier=repas,
                type_suivi=SuiviRepas.TypeSuivi.COMPTAGE,
                effectif_attendu=1,
                nombre_ayant_mange=2,
            )


class RavitaillementServiceTests(RepasFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.creer_affectation(1)
        self.creer_affectation(2)

    def test_creation_calcule_effectif_sans_saisie_humaine(self):
        demande = RavitaillementService.creer_demande(
            acteur=self.agent,
            session_id=self.session.id,
            centre_id=self.centre.id,
        )
        self.assertEqual(demande.effectif_reference, 2)

    def test_cycle_soumission_validation_reception(self):
        demande = self.creer_demande_validee()
        ligne = LigneBesoinDenreeRepository.non_supprimees().get(
            demande_ravitaillement_id=demande.id
        )
        self.assertEqual(demande.statut, demande.Statut.VALIDEE)
        self.assertEqual(ligne.quantite_validee, Decimal("10"))
        ligne = RavitaillementService.enregistrer_reception(
            ligne.id, acteur=self.agent, quantite_recue=Decimal("8")
        )
        self.assertEqual(ligne.statut, ligne.Statut.PARTIELLEMENT_RECUE)
        ligne = RavitaillementService.enregistrer_reception(
            ligne.id, acteur=self.agent, quantite_recue=Decimal("10")
        )
        self.assertEqual(ligne.statut, ligne.Statut.RECUE)

    def test_module_desactive_bloque_creation(self):
        self.session.parametres.repas_active = False
        self.session.parametres.save(update_fields=["repas_active", "updated_at"])
        with self.assertRaises(ValidationRepasErreur):
            RavitaillementService.creer_demande(
                acteur=self.agent,
                session_id=self.session.id,
                centre_id=self.centre.id,
            )

    def test_consolidation_agrege_les_quantites(self):
        self.creer_demande_validee()
        resultat = RavitaillementService.consolider(
            acteur=self.agent, session_id=self.session.id
        )
        self.assertEqual(len(resultat), 1)
        self.assertEqual(resultat[0]["code_denree"], "RIZ")


class IntegrationSanteRepasTests(RepasFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.affectation = self.creer_affectation(1)
        self.creer_affectation(2)
        self.restriction = self.creer_restriction_repas(self.affectation)
        self.demande = self.creer_demande_validee()

    def test_besoins_groupes_n_exposent_pas_diagnostic(self):
        resultat = ImpactMedicalService.besoins_repas_pour_date(
            session_id=self.session.id,
            centre_id=self.centre.id,
            date_reference=self.date_repas,
        )
        self.assertEqual(resultat["total_concernes"], 1)
        self.assertEqual(resultat["synthese"]["SANS_ARACHIDE"], 1)
        texte = str(resultat)
        self.assertNotIn("Allergie confidentielle", texte)
        self.assertIn("Préparer un repas sans arachide", texte)

    def test_creation_calcule_standard_et_synthese(self):
        repas = self.creer_repas()
        self.assertEqual(repas.nombre_standard_prevu, 1)
        self.assertEqual(
            repas.synthese_restrictions_alimentaires, {"SANS_ARACHIDE": 1}
        )
        self.assertEqual(
            repas.statut_controle_sante,
            RepasJournalier.StatutControleSante.A_JOUR,
        )

    def test_validation_refuse_preparation_speciale_manquante(self):
        repas = self.creer_repas()
        RepasService.planifier(repas.id, acteur=self.agent)
        with self.assertRaises(ValidationRepasErreur):
            RepasService.valider_planification(repas.id, acteur=self.agent)

    def test_validation_cree_suivi_medical_automatiquement(self):
        repas = self.creer_repas(
            preparations={
                "SANS_ARACHIDE": {
                    "menu": "Riz gras avec sauce sans arachide",
                    "quantite": 1,
                }
            }
        )
        RepasService.planifier(repas.id, acteur=self.agent)
        repas = RepasService.valider_planification(repas.id, acteur=self.agent)
        suivi = SuiviRepas.objects.get(
            repas_journalier=repas,
            type_suivi=SuiviRepas.TypeSuivi.MEDICAL,
        )
        self.assertEqual(suivi.affectation_centre_id, self.affectation.id)
        self.assertEqual(suivi.statut_service, SuiviRepas.StatutService.A_SERVIR)
        self.assertNotIn("Allergie", suivi.consigne_alimentaire)

    def test_modification_restriction_marque_repas_a_revoir(self):
        repas = self.creer_repas(
            preparations={
                "SANS_ARACHIDE": {"menu": "Menu adapté", "quantite": 1}
            }
        )
        RepasService.planifier(repas.id, acteur=self.agent)
        RepasService.valider_planification(repas.id, acteur=self.agent)
        self.restriction.consigne_operationnelle = "Nouvelle consigne alimentaire"
        self.restriction.save()
        repas.refresh_from_db()
        self.assertEqual(
            repas.statut_controle_sante,
            RepasJournalier.StatutControleSante.A_REVOIR,
        )


class ParcoursDistributionTests(RepasFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.affectation = self.creer_affectation(1)
        self.creer_affectation(2)
        self.creer_restriction_repas(self.affectation)
        self.demande = self.creer_demande_validee()
        self.repas = self.creer_repas(
            preparations={
                "SANS_ARACHIDE": {"menu": "Menu adapté", "quantite": 1}
            }
        )
        RepasService.planifier(self.repas.id, acteur=self.agent)
        RepasService.valider_planification(self.repas.id, acteur=self.agent)

    def test_parcours_complet_jusqu_a_cloture(self):
        RepasService.demarrer_preparation(self.repas.id, acteur=self.agent)
        self.repas = RepasService.terminer_preparation(
            self.repas.id,
            acteur=self.agent,
            menu_prepare="Riz gras",
            nombre_standard_prepare=1,
            preparations_speciales_reelles={
                "SANS_ARACHIDE": {"menu": "Menu adapté", "quantite": 1}
            },
        )
        self.repas = RepasService.ouvrir_distribution(
            self.repas.id, acteur=self.agent
        )
        comptage = SuiviRepas.objects.get(
            repas_journalier=self.repas,
            type_suivi=SuiviRepas.TypeSuivi.COMPTAGE,
        )
        RepasService.saisir_comptage(
            comptage.id, acteur=self.agent, nombre_ayant_mange=2
        )
        medical = SuiviRepas.objects.get(
            repas_journalier=self.repas,
            type_suivi=SuiviRepas.TypeSuivi.MEDICAL,
        )
        RepasService.marquer_service_medical(
            medical.id,
            acteur=self.agent,
            statut_service=SuiviRepas.StatutService.SERVI_CONFORME,
        )
        self.repas = RepasService.cloturer(self.repas.id, acteur=self.agent)
        self.assertEqual(self.repas.statut, RepasJournalier.Statut.CLOTURE)

    def test_cloture_refuse_suivi_medical_en_attente(self):
        RepasService.demarrer_preparation(self.repas.id, acteur=self.agent)
        RepasService.terminer_preparation(
            self.repas.id,
            acteur=self.agent,
            menu_prepare="Riz gras",
            nombre_standard_prepare=1,
            preparations_speciales_reelles={
                "SANS_ARACHIDE": {"menu": "Menu adapté", "quantite": 1}
            },
        )
        RepasService.ouvrir_distribution(self.repas.id, acteur=self.agent)
        with self.assertRaises(ValidationRepasErreur):
            RepasService.cloturer(self.repas.id, acteur=self.agent)


@override_settings(CACHES=CACHE_TEST)
class TachesRepasTests(RepasFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.creer_socle(visite_medicale_active=False)
        self.creer_affectation(1)
        self.demande = self.creer_demande_validee()
        self.repas = self.creer_repas()

    def test_progression_absente_est_en_attente(self):
        progression = ProgressionRepasService.lire("inconnue")
        self.assertEqual(progression["statut"], ProgressionRepasService.EN_ATTENTE)

    def test_tache_prepare_comptage_et_stocke_progression(self):
        RepasService.planifier(self.repas.id, acteur=self.agent)
        RepasService.valider_planification(self.repas.id, acteur=self.agent)
        resultat = preparer_suivis_repas_task.apply(
            kwargs={"repas_id": self.repas.id, "acteur_id": self.agent.id},
            task_id="test-preparation-repas",
        ).get()
        self.assertEqual(resultat["statut"], ProgressionRepasService.TERMINEE)
        self.assertTrue(
            SuiviRepas.objects.filter(
                repas_journalier=self.repas,
                type_suivi=SuiviRepas.TypeSuivi.COMPTAGE,
            ).exists()
        )


class SerializersEtSeedTests(TestCase):
    def test_serializer_creation_repas_valide_structure_minimale(self):
        serializer = RepasCreateSerializer(
            data={
                "demande_ravitaillement_id": 1,
                "date_repas": "2026-08-10",
                "type_repas": "DEJEUNER",
                "menu_prevu": "Riz gras",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_serializer_service_interdit_a_servir_comme_statut_final(self):
        serializer = ServiceMedicalSerializer(
            data={"statut_service": "A_SERVIR"}
        )
        self.assertFalse(serializer.is_valid())

    def test_seed_contient_permissions_repas_sans_doublon(self):
        codes = [definition.code for definition in PERMISSIONS_SYSTEME]
        self.assertIn("planifier_repas", codes)
        self.assertIn("consolider_besoins_denrees", codes)
        self.assertIn("consulter_progression_repas", codes)
        self.assertEqual(len(codes), len(set(codes)))
