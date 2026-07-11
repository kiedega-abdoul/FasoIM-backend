from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.management.commands.seed_accounts import (
    PERMISSIONS_SYSTEME,
)
from accounts.models import Acteur
from affectations.models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)
from immerges.models import Immerge
from sessions_app.models import ParametreSession, SessionImmersion

from .models import RestrictionMedicale, VisiteMedicale
from .permissions import (
    PermissionImpactMedical,
    PermissionRestrictionMedicale,
    PermissionVisiteMedicale,
)
from .repository import (
    CandidatVisiteMedicaleRepository,
    RestrictionMedicaleRepository,
    VisiteMedicaleRepository,
)
from .serializers import (
    EnregistrementVisiteMedicaleInputSerializer,
    FiltreRestrictionMedicaleSerializer,
    FiltreVisiteMedicaleSerializer,
    RestrictionMedicaleInputSerializer,
)
from .service import (
    ImpactMedicalService,
    RestrictionMedicaleService,
    ValidationSanteErreur,
    VisiteMedicaleService,
)


class SanteFixtureMixin:
    mot_de_passe = "Test-Sante-2026!"

    def creer_socle(self, *, visite_medicale_active=True):
        self.agent = Acteur.objects.create_user(
            username="agent-sante-tests",
            email="agent-sante-tests@fasoim.test",
            password=self.mot_de_passe,
            first_name="Agent",
            last_name="Santé",
        )
        self.session = SessionImmersion.objects.create(
            nom="Session santé 2026",
            annee=2026,
            numero_promotion=2,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=timezone.localdate() + timedelta(days=10),
            date_fin=timezone.localdate() + timedelta(days=40),
            statut=SessionImmersion.Statut.EN_PREPARATION,
        )
        self.parametres = ParametreSession.objects.create(
            session=self.session,
            visite_medicale_active=visite_medicale_active,
            hebergement_active=True,
            repas_active=True,
            activites_active=True,
            evaluation_active=True,
        )
        self.region = RegionImmersion.objects.create(
            code="REG-SANTE",
            nom="Région santé",
        )
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="CTR-SANTE-001",
            nom="Centre santé",
            province="Kadiogo",
            ville="Ouagadougou",
            capacite_totale=200,
            genre=CentreImmersion.Genre.MIXTE,
            publics_acceptes=[],
            niveaux_acceptes=[],
        )

    def creer_affectation(self, numero):
        immerge = Immerge.objects.create(
            session=self.session,
            type_immerge=Immerge.TypeImmerge.SELECTIONNE,
            origine_id=20_000 + numero,
            code_fasoim=f"IP2026SEL02{numero:05d}",
            statut=Immerge.Statut.AFFECTE_CENTRE,
        )
        affectation_regionale = AffectationRegionale.objects.create(
            immerge=immerge,
            session=self.session,
            region=self.region,
            statut=AffectationRegionale.Statut.ACTIVE,
            affecte_par=self.agent,
        )
        return AffectationCentre.objects.create(
            immerge=immerge,
            session=self.session,
            affectation_regionale=affectation_regionale,
            centre=self.centre,
            statut=AffectationCentre.Statut.ACTIVE,
            affecte_par=self.agent,
        )

    def creer_visite(
        self,
        affectation,
        *,
        resultat=VisiteMedicale.Resultat.APTE,
        validee=True,
        numero_visite=1,
    ):
        visite = VisiteMedicale.objects.create(
            affectation_centre=affectation,
            numero_visite=numero_visite,
            resultat=resultat,
            agent_sante=self.agent,
        )
        if validee:
            visite.valider(agent_sante=self.agent)
        return visite

    def creer_restriction(
        self,
        visite,
        *,
        module=RestrictionMedicale.ModuleConcerne.ACTIVITES,
        type_restriction=(
            RestrictionMedicale.TypeRestriction.ADAPTATION
        ),
        date_fin=None,
    ):
        return RestrictionMedicale.objects.create(
            visite_medicale=visite,
            libelle="Restriction de test",
            type_restriction=type_restriction,
            modules_concernes=[module],
            description_medicale="Donnée médicale confidentielle.",
            consigne_operationnelle=(
                "Adapter l'action sans exposer le diagnostic."
            ),
            date_fin=date_fin,
            saisie_par=self.agent,
        )


class ModelesSanteTests(SanteFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.affectation = self.creer_affectation(1)

    def test_dispense_autorise_l_immersion(self):
        visite = self.creer_visite(
            self.affectation,
            resultat=VisiteMedicale.Resultat.DISPENSE,
        )

        self.assertTrue(visite.autorise_immersion)
        self.assertFalse(visite.necessite_retrait_organisation)

    def test_visite_copie_session_et_centre_depuis_affectation(self):
        visite = self.creer_visite(
            self.affectation,
            validee=False,
        )

        self.assertEqual(visite.session_id, self.session.id)
        self.assertEqual(visite.centre_id, self.centre.id)

    def test_visite_refuse_session_sans_module_medical(self):
        self.parametres.visite_medicale_active = False
        self.parametres.save()

        with self.assertRaises(ValidationError):
            VisiteMedicale.objects.create(
                affectation_centre=self.affectation,
                resultat=VisiteMedicale.Resultat.APTE,
                agent_sante=self.agent,
            )

    def test_validation_exige_un_resultat(self):
        visite = VisiteMedicale.objects.create(
            affectation_centre=self.affectation,
            resultat="",
            agent_sante=self.agent,
        )

        with self.assertRaises(ValidationError):
            visite.valider(agent_sante=self.agent)

    def test_prochaine_visite_reservee_a_inaptitude_temporaire(self):
        with self.assertRaises(ValidationError):
            VisiteMedicale.objects.create(
                affectation_centre=self.affectation,
                resultat=VisiteMedicale.Resultat.APTE,
                date_prochaine_visite=(
                    timezone.localdate() + timedelta(days=7)
                ),
                agent_sante=self.agent,
            )

    def test_une_seule_visite_courante_par_affectation(self):
        self.creer_visite(
            self.affectation,
            validee=False,
            numero_visite=1,
        )

        with self.assertRaises(
            (ValidationError, IntegrityError)
        ):
            VisiteMedicale.objects.create(
                affectation_centre=self.affectation,
                numero_visite=2,
                resultat=VisiteMedicale.Resultat.APTE,
                agent_sante=self.agent,
            )

    def test_valider_prepare_application_du_resultat(self):
        visite = self.creer_visite(
            self.affectation,
            validee=False,
        )

        visite.valider(agent_sante=self.agent)

        self.assertEqual(
            visite.statut,
            VisiteMedicale.Statut.VALIDEE,
        )
        self.assertEqual(
            visite.statut_application,
            VisiteMedicale.StatutApplication.A_APPLIQUER,
        )
        self.assertIsNotNone(visite.date_validation)

    def test_modules_restriction_sont_dedoublonnes(self):
        visite = self.creer_visite(
            self.affectation,
            validee=False,
        )
        restriction = RestrictionMedicale.objects.create(
            visite_medicale=visite,
            libelle="Adaptation",
            modules_concernes=[
                RestrictionMedicale.ModuleConcerne.ACTIVITES,
                RestrictionMedicale.ModuleConcerne.ACTIVITES,
                RestrictionMedicale.ModuleConcerne.EVALUATIONS,
            ],
            consigne_operationnelle="Adapter les activités.",
            saisie_par=self.agent,
        )

        self.assertEqual(
            restriction.modules_concernes,
            [
                RestrictionMedicale.ModuleConcerne.ACTIVITES,
                RestrictionMedicale.ModuleConcerne.EVALUATIONS,
            ],
        )

    def test_restriction_refuse_un_module_inconnu(self):
        visite = self.creer_visite(
            self.affectation,
            validee=False,
        )

        with self.assertRaises(ValidationError):
            RestrictionMedicale.objects.create(
                visite_medicale=visite,
                libelle="Module inconnu",
                modules_concernes=["MODULE_INCONNU"],
                consigne_operationnelle="Consigne.",
                saisie_par=self.agent,
            )

    def test_restriction_refuse_dates_incoherentes(self):
        visite = self.creer_visite(
            self.affectation,
            validee=False,
        )

        with self.assertRaises(ValidationError):
            RestrictionMedicale.objects.create(
                visite_medicale=visite,
                libelle="Dates incohérentes",
                modules_concernes=[
                    RestrictionMedicale.ModuleConcerne.REPAS
                ],
                consigne_operationnelle="Adapter le repas.",
                date_debut=timezone.localdate(),
                date_fin=timezone.localdate() - timedelta(days=1),
                saisie_par=self.agent,
            )

    def test_restriction_applicable_exige_visite_validee(self):
        visite = self.creer_visite(
            self.affectation,
            validee=False,
        )
        restriction = self.creer_restriction(visite)

        self.assertFalse(restriction.est_applicable)

        visite.valider(agent_sante=self.agent)
        restriction.refresh_from_db()

        self.assertTrue(restriction.est_applicable)

    def test_lever_restriction_conserve_historique(self):
        visite = self.creer_visite(self.affectation)
        restriction = self.creer_restriction(visite)

        restriction.lever(
            motif="Restriction terminée.",
            levee_par=self.agent,
        )

        self.assertEqual(
            restriction.statut,
            RestrictionMedicale.Statut.LEVEE,
        )
        self.assertIsNotNone(restriction.date_levee)
        self.assertIsNone(restriction.deleted_at)


class RepositoriesSanteTests(SanteFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.affectation_1 = self.creer_affectation(1)
        self.affectation_2 = self.creer_affectation(2)

    def test_repository_retrouve_visite_courante(self):
        visite = self.creer_visite(self.affectation_1)

        retrouvee = (
            VisiteMedicaleRepository
            .get_courante_par_affectation(
                self.affectation_1.id
            )
        )

        self.assertEqual(retrouvee.id, visite.id)

    def test_candidats_sans_visite_excluent_deja_visite(self):
        self.creer_visite(self.affectation_1)

        ids = list(
            CandidatVisiteMedicaleRepository
            .sans_visite_courante(
                session_id=self.session.id,
                centre_id=self.centre.id,
            )
            .values_list("id", flat=True)
        )

        self.assertEqual(ids, [self.affectation_2.id])

    def test_prochaine_affectation_retourne_immerge_suivant(self):
        suivante = (
            CandidatVisiteMedicaleRepository
            .prochaine_affectation(
                session_id=self.session.id,
                centre_id=self.centre.id,
                apres_affectation_id=self.affectation_1.id,
            )
        )

        self.assertEqual(suivante.id, self.affectation_2.id)

    def test_repository_filtre_restrictions_par_module(self):
        visite = self.creer_visite(self.affectation_1)
        restriction = self.creer_restriction(
            visite,
            module=(
                RestrictionMedicale.ModuleConcerne.EVALUATIONS
            ),
        )

        ids = list(
            RestrictionMedicaleRepository
            .applicables_pour_affectation_module(
                affectation_centre_id=self.affectation_1.id,
                module=(
                    RestrictionMedicale.ModuleConcerne.EVALUATIONS
                ),
            )
            .values_list("id", flat=True)
        )

        self.assertEqual(ids, [restriction.id])

    def test_statistiques_comptent_seulement_visites_validees(self):
        self.creer_visite(
            self.affectation_1,
            resultat=VisiteMedicale.Resultat.APTE,
        )
        self.creer_visite(
            self.affectation_2,
            resultat=VisiteMedicale.Resultat.INAPTE_TEMPORAIRE,
        )

        statistiques = {
            ligne["resultat"]: ligne["total"]
            for ligne in VisiteMedicaleRepository.statistiques(
                session_id=self.session.id,
                centre_id=self.centre.id,
            )
        }

        self.assertEqual(
            statistiques[VisiteMedicale.Resultat.APTE],
            1,
        )
        self.assertEqual(
            statistiques[
                VisiteMedicale.Resultat.INAPTE_TEMPORAIRE
            ],
            1,
        )


class SerializersSanteTests(SimpleTestCase):
    def restriction_valide(self, *, module="ACTIVITES"):
        return {
            "libelle": "Restriction",
            "type_restriction": "ADAPTATION",
            "modules_concernes": [module],
            "consigne_operationnelle": "Adapter la prise en charge.",
        }

    def test_apte_sous_reserve_exige_restriction(self):
        serializer = EnregistrementVisiteMedicaleInputSerializer(
            data={
                "affectation_centre_id": 1,
                "resultat": "APTE_SOUS_RESERVE",
                "restrictions": [],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("restrictions", serializer.errors)

    def test_dispense_exige_restriction(self):
        serializer = EnregistrementVisiteMedicaleInputSerializer(
            data={
                "affectation_centre_id": 1,
                "resultat": "DISPENSE",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("restrictions", serializer.errors)

    def test_apte_sans_restriction_est_valide(self):
        serializer = EnregistrementVisiteMedicaleInputSerializer(
            data={
                "affectation_centre_id": 1,
                "resultat": "APTE",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_date_contre_visite_refusee_pour_apte(self):
        serializer = EnregistrementVisiteMedicaleInputSerializer(
            data={
                "affectation_centre_id": 1,
                "resultat": "APTE",
                "date_prochaine_visite": (
                    timezone.localdate() + timedelta(days=5)
                ),
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "date_prochaine_visite",
            serializer.errors,
        )

    def test_filtre_visites_exige_un_perimetre(self):
        serializer = FiltreVisiteMedicaleSerializer(data={})

        self.assertFalse(serializer.is_valid())

    def test_filtre_restrictions_exige_un_perimetre(self):
        serializer = FiltreRestrictionMedicaleSerializer(data={})

        self.assertFalse(serializer.is_valid())

    def test_serializer_restriction_dedoublonne_modules(self):
        serializer = RestrictionMedicaleInputSerializer(
            data={
                **self.restriction_valide(),
                "modules_concernes": [
                    "ACTIVITES",
                    "ACTIVITES",
                    "EVALUATIONS",
                ],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["modules_concernes"],
            ["ACTIVITES", "EVALUATIONS"],
        )


class ServicesSanteTests(SanteFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.affectation_1 = self.creer_affectation(1)
        self.affectation_2 = self.creer_affectation(2)

    def donnees_restriction(
        self,
        *,
        module,
        type_restriction="ADAPTATION",
    ):
        return {
            "libelle": "Restriction opérationnelle",
            "type_restriction": type_restriction,
            "modules_concernes": [module],
            "description_medicale": "Information confidentielle.",
            "consigne_operationnelle": "Adapter la prise en charge.",
        }

    def test_brouillon_est_modifie_sans_creer_doublon(self):
        premiere = (
            VisiteMedicaleService.creer_ou_modifier_brouillon(
                affectation_centre_id=self.affectation_1.id,
                acteur=self.agent,
                resultat="APTE",
            )
        )
        seconde = (
            VisiteMedicaleService.creer_ou_modifier_brouillon(
                affectation_centre_id=self.affectation_1.id,
                acteur=self.agent,
                observations_medicales="Observation corrigée.",
            )
        )

        self.assertEqual(premiere.id, seconde.id)
        self.assertEqual(VisiteMedicale.objects.count(), 1)
        self.assertEqual(
            seconde.observations_medicales,
            "Observation corrigée.",
        )

    def test_enregistrement_apte_applique_et_charge_suivant(self):
        resultat = VisiteMedicaleService.enregistrer_et_appliquer(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
            resultat="APTE",
        )

        visite = VisiteMedicale.objects.get(
            id=resultat.visite_medicale_id
        )
        self.assertEqual(
            visite.statut_application,
            VisiteMedicale.StatutApplication.APPLIQUEE,
        )
        self.assertEqual(
            resultat.prochaine_affectation_centre_id,
            self.affectation_2.id,
        )
        self.assertEqual(
            resultat.application["organisation"]["action"],
            "ORGANISATION_CONSERVEE",
        )

    @patch(
        "sante.service."
        "VisiteMedicaleOrganisationService.appliquer_resultat"
    )
    def test_apte_sous_reserve_reorganise_seulement_hebergement(
        self,
        appliquer_resultat,
    ):
        appliquer_resultat.return_value = {
            "affectation_centre_id": self.affectation_1.id,
            "resultat": "APTE_SOUS_RESERVE",
            "action": "A_REORGANISER",
        }

        resultat = VisiteMedicaleService.enregistrer_et_appliquer(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
            resultat="APTE_SOUS_RESERVE",
            restrictions=[
                self.donnees_restriction(
                    module="HEBERGEMENT",
                )
            ],
        )

        appliquer_resultat.assert_called_once_with(
            affectation_centre_id=self.affectation_1.id,
            resultat="APTE_SOUS_RESERVE",
            observations="",
            reorganiser_groupe=False,
            reorganiser_lit=True,
        )
        decision = (
            resultat.application["decisions_modules"][
                "HEBERGEMENT"
            ]
        )
        self.assertTrue(decision["necessite_adaptation"])

    @patch(
        "sante.service."
        "VisiteMedicaleOrganisationService.appliquer_resultat"
    )
    def test_dispense_evaluation_conserve_organisation(
        self,
        appliquer_resultat,
    ):
        resultat = VisiteMedicaleService.enregistrer_et_appliquer(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
            resultat="DISPENSE",
            restrictions=[
                self.donnees_restriction(
                    module="EVALUATIONS",
                    type_restriction="DISPENSE",
                )
            ],
        )

        appliquer_resultat.assert_not_called()
        self.assertEqual(
            resultat.application["organisation"]["action"],
            "DISPENSE_ORGANISATION_CONSERVEE",
        )
        decision = (
            resultat.application["decisions_modules"][
                "EVALUATIONS"
            ]
        )
        self.assertFalse(decision["autorise"])
        self.assertTrue(decision["dispense"])

    @patch(
        "sante.service."
        "VisiteMedicaleOrganisationService.appliquer_resultat"
    )
    def test_inapte_temporaire_est_transmis_a_organisation(
        self,
        appliquer_resultat,
    ):
        appliquer_resultat.return_value = {
            "affectation_centre_id": self.affectation_1.id,
            "resultat": "INAPTE_TEMPORAIRE",
            "action": "RETIRE_DE_L_ORGANISATION",
        }

        VisiteMedicaleService.enregistrer_et_appliquer(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
            resultat="INAPTE_TEMPORAIRE",
            date_prochaine_visite=(
                timezone.localdate() + timedelta(days=10)
            ),
        )

        appliquer_resultat.assert_called_once_with(
            affectation_centre_id=self.affectation_1.id,
            resultat="INAPTE_TEMPORAIRE",
            observations="",
        )

    @patch(
        "sante.service."
        "VisiteMedicaleOrganisationService.appliquer_resultat"
    )
    def test_contre_visite_conserve_historique(
        self,
        appliquer_resultat,
    ):
        appliquer_resultat.return_value = {
            "affectation_centre_id": self.affectation_1.id,
            "resultat": "INAPTE_TEMPORAIRE",
            "action": "RETIRE_DE_L_ORGANISATION",
        }
        premiere = VisiteMedicaleService.enregistrer_et_appliquer(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
            resultat="APTE",
        )

        seconde = VisiteMedicaleService.corriger_par_contre_visite(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
            resultat="INAPTE_TEMPORAIRE",
            date_prochaine_visite=(
                timezone.localdate() + timedelta(days=7)
            ),
        )

        ancienne = VisiteMedicale.objects.get(
            id=premiere.visite_medicale_id
        )
        nouvelle = VisiteMedicale.objects.get(
            id=seconde.visite_medicale_id
        )
        self.assertFalse(ancienne.est_courante)
        self.assertTrue(nouvelle.est_courante)
        self.assertEqual(nouvelle.numero_visite, 2)
        self.assertEqual(
            VisiteMedicale.objects.filter(
                affectation_centre=self.affectation_1
            ).count(),
            2,
        )

    def test_impact_bloque_avant_visite(self):
        decision = ImpactMedicalService.decision_pour_module(
            affectation_centre_id=self.affectation_1.id,
            module="ACTIVITES",
        )

        self.assertEqual(decision["etat"], "EN_ATTENTE_VISITE")
        self.assertFalse(decision["autorise"])

    def test_impact_apte_autorise_action(self):
        self.creer_visite(self.affectation_1)

        decision = ImpactMedicalService.decision_pour_module(
            affectation_centre_id=self.affectation_1.id,
            module="ACTIVITES",
        )

        self.assertEqual(decision["etat"], "AUTORISE")
        self.assertTrue(decision["autorise"])

    def test_consigne_operationnelle_ne_divulgue_pas_diagnostic(self):
        visite = self.creer_visite(self.affectation_1)
        self.creer_restriction(
            visite,
            module=RestrictionMedicale.ModuleConcerne.REPAS,
        )

        consignes = (
            RestrictionMedicaleService.consignes_pour_module(
                affectation_centre_id=self.affectation_1.id,
                module="REPAS",
            )
        )

        self.assertEqual(len(consignes), 1)
        self.assertNotIn("description_medicale", consignes[0])
        self.assertIn("consigne_operationnelle", consignes[0])

    def test_verifier_action_leve_erreur_pour_dispense(self):
        visite = self.creer_visite(
            self.affectation_1,
            resultat=VisiteMedicale.Resultat.DISPENSE,
        )
        self.creer_restriction(
            visite,
            module=(
                RestrictionMedicale.ModuleConcerne.EVALUATIONS
            ),
            type_restriction=(
                RestrictionMedicale.TypeRestriction.DISPENSE
            ),
        )

        with self.assertRaises(ValidationSanteErreur):
            ImpactMedicalService.verifier_action_autorisee(
                affectation_centre_id=self.affectation_1.id,
                module="EVALUATIONS",
            )


class PermissionsRoutesEtSeedSanteTests(SimpleTestCase):
    def test_permissions_correspondent_aux_actions_api(self):
        self.assertEqual(
            PermissionVisiteMedicale.action_permission_map[
                "create"
            ],
            "saisir_resultat_visite_medicale",
        )
        self.assertEqual(
            PermissionVisiteMedicale.action_permission_map[
                "contre_visite"
            ],
            "corriger_resultat_visite_medicale",
        )
        self.assertEqual(
            PermissionRestrictionMedicale.action_permission_map[
                "lever"
            ],
            "lever_restriction_medicale",
        )
        self.assertEqual(
            PermissionImpactMedical.action_permission_map[
                "retrieve"
            ],
            "consulter_impacts_medicaux",
        )

    def test_routes_sante_principales_sont_resolues(self):
        attentes = {
            "/api/sante/visites/": (
                "sante:visites-medicales-list"
            ),
            "/api/sante/restrictions/": (
                "sante:restrictions-medicales-list"
            ),
            "/api/sante/impacts/1/": (
                "sante:impacts-medicaux-detail"
            ),
            "/api/sante/visites/brouillon/": (
                "sante:visites-medicales-brouillon"
            ),
            "/api/sante/visites/contre-visite/": (
                "sante:visites-medicales-contre-visite"
            ),
        }

        for chemin, nom_vue in attentes.items():
            with self.subTest(chemin=chemin):
                self.assertEqual(resolve(chemin).view_name, nom_vue)

    def test_reverse_route_visites(self):
        self.assertEqual(
            reverse("sante:visites-medicales-list"),
            "/api/sante/visites/",
        )

    def test_permissions_sante_sont_dans_seed_accounts(self):
        codes_seed = {
            definition.code
            for definition in PERMISSIONS_SYSTEME
            if definition.module == "sante"
        }
        codes_attendus = {
            "consulter_visites_medicales",
            "saisir_resultat_visite_medicale",
            "corriger_resultat_visite_medicale",
            "appliquer_resultat_visite_medicale",
            "annuler_visite_medicale",
            "consulter_candidats_visite_medicale",
            "consulter_statistiques_sante",
            "consulter_restrictions_medicales",
            "enregistrer_restriction_medicale",
            "modifier_restriction_medicale",
            "annuler_restriction_medicale",
            "lever_restriction_medicale",
            "consulter_impacts_medicaux",
        }

        self.assertEqual(codes_seed, codes_attendus)


class ApiSanteNonAuthentifieeTests(TestCase):
    def test_api_visites_refuse_utilisateur_non_authentifie(self):
        reponse = APIClient().get(
            "/api/sante/visites/",
            {"session_id": 1},
        )

        self.assertIn(reponse.status_code, {401, 403})

    def test_api_impacts_refuse_utilisateur_non_authentifie(self):
        reponse = APIClient().get(
            "/api/sante/impacts/1/",
            {"module": "ACTIVITES"},
        )

        self.assertIn(reponse.status_code, {401, 403})
