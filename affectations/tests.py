from datetime import date
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse
from rest_framework.test import APIClient

from immerges.models import Immerge
from sessions_app.models import SessionImmersion
from organisation.models import RegleOrganisationCentre

from .models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)
from .permissions import (
    PermissionAffectationCentre,
    PermissionAffectationRegionale,
    PermissionCentreImmersion,
    PermissionRegionImmersion,
)
from .repository import (
    STATUTS_CENTRES_OUVERTS,
    STATUTS_REGIONAUX_OUVERTS,
    CentreImmersionRepository,
)
from .serializers import (
    CentreImmersionInputSerializer,
    PropositionCentreLotInputSerializer,
    PropositionRegionaleLotInputSerializer,
    RejetAffectationsLotInputSerializer,
    ValidationAffectationsLotInputSerializer,
)
from .service import (
    AffectationCentreService,
    AffectationRegionaleService,
    CapaciteAffectationService,
    NormalisationGeographiqueService,
    ProfilAffectation,
    ValidationAffectationErreur,
)
from .tasks import ProgressionAffectationService


class ModelesAffectationsTests(TestCase):
    def setUp(self):
        self.region = RegionImmersion.objects.create(
            code="CENTRE",
            nom="Centre",
        )
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="CENTRE-001",
            nom="Centre principal",
            province="Kadiogo",
            ville="Ouagadougou",
            genre=CentreImmersion.Genre.MIXTE,
            publics_acceptes=["BEPC", "BAC"],
            niveaux_acceptes=["BEPC", "BAC_D"],
        )

    def test_statut_proposee_est_le_defaut_des_affectations(self):
        self.assertEqual(
            AffectationRegionale._meta.get_field("statut").default,
            AffectationRegionale.Statut.PROPOSEE,
        )
        self.assertEqual(
            AffectationCentre._meta.get_field("statut").default,
            AffectationCentre.Statut.PROPOSEE,
        )

    def test_statuts_ouverts_reservent_les_places(self):
        self.assertEqual(
            set(STATUTS_REGIONAUX_OUVERTS),
            {
                AffectationRegionale.Statut.PROPOSEE,
                AffectationRegionale.Statut.ACTIVE,
            },
        )
        self.assertEqual(
            set(STATUTS_CENTRES_OUVERTS),
            {
                AffectationCentre.Statut.PROPOSEE,
                AffectationCentre.Statut.ACTIVE,
            },
        )

    def test_centre_refuse_un_json_non_liste(self):
        self.centre.publics_acceptes = "BAC"
        self.centre.niveaux_acceptes = {"BAC"}

        with self.assertRaises(ValidationError) as contexte:
            self.centre.full_clean()

        self.assertIn("publics_acceptes", contexte.exception.message_dict)
        self.assertIn("niveaux_acceptes", contexte.exception.message_dict)

    def test_suppression_logique_region_brouille_le_code(self):
        region_sans_centre = RegionImmersion.objects.create(
            code="BOUCLE-MOUHOUN",
            nom="Boucle du Mouhoun",
        )
        ancien_code = region_sans_centre.code

        region_sans_centre.supprimer_logiquement()
        region_sans_centre.refresh_from_db()

        self.assertIsNotNone(region_sans_centre.deleted_at)
        self.assertEqual(
            region_sans_centre.statut,
            RegionImmersion.Statut.DESACTIVEE,
        )
        self.assertNotEqual(region_sans_centre.code, ancien_code)
        self.assertIn("SUPPRIME", region_sans_centre.code)

    def test_suppression_logique_centre_brouille_le_code(self):
        ancien_code = self.centre.code

        self.centre.supprimer_logiquement()
        self.centre.refresh_from_db()

        self.assertIsNotNone(self.centre.deleted_at)
        self.assertEqual(
            self.centre.statut,
            CentreImmersion.Statut.DESACTIVE,
        )
        self.assertNotEqual(self.centre.code, ancien_code)
        self.assertIn("SUPPRIME", self.centre.code)

    def test_repository_expose_le_vrai_champ_niveaux_acceptes(self):
        ligne = CentreImmersionRepository.lister_donnees_algorithme().get(
            id=self.centre.id
        )

        self.assertIn("niveaux_acceptes", ligne)
        self.assertNotIn("niveaux_examens_acceptes", ligne)
        self.assertEqual(ligne["niveaux_acceptes"], ["BEPC", "BAC_D"])

    def test_capacite_region_est_somme_des_centres_actifs(self):
        centre_secondaire = CentreImmersion.objects.create(
            region=self.region,
            code="CENTRE-002",
            nom="Centre secondaire",
            province="Kadiogo",
            ville="Ouagadougou",
        )
        session = SessionImmersion.objects.create(
            nom="Session capacité régionale 2026",
            annee=2026,
            numero_promotion=99,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=date(2026, 8, 1),
            date_fin=date(2026, 8, 31),
            statut=SessionImmersion.Statut.EN_PREPARATION,
        )
        RegleOrganisationCentre.objects.create(
            session=session,
            centre=self.centre,
            capacite_ouverte=100,
            seuil_division_sections=100,
            capacite_max_section=100,
            seuil_division_groupes=50,
            capacite_max_groupe=50,
            statut=RegleOrganisationCentre.Statut.VALIDEE,
        )
        RegleOrganisationCentre.objects.create(
            session=session,
            centre=centre_secondaire,
            capacite_ouverte=40,
            seuil_division_sections=40,
            capacite_max_section=40,
            seuil_division_groupes=20,
            capacite_max_groupe=20,
            statut=RegleOrganisationCentre.Statut.VALIDEE,
        )

        capacites = CapaciteAffectationService.capacites_regions(
            session_id=session.id,
            region_ids=[self.region.id],
        )

        self.assertEqual(
            capacites[self.region.id]["capacite_totale"],
            140,
        )
        self.assertEqual(
            capacites[self.region.id]["occupation_ouverte"],
            0,
        )
        self.assertEqual(
            capacites[self.region.id]["disponible"],
            140,
        )

    def test_proposition_regionale_peut_etre_validee(self):
        affectation = AffectationRegionale(
            statut=AffectationRegionale.Statut.PROPOSEE,
        )

        with (
            patch.object(AffectationRegionale, "full_clean") as full_clean,
            patch.object(AffectationRegionale, "save") as sauvegarder,
        ):
            resultat = affectation.valider()

        self.assertIs(resultat, affectation)
        self.assertEqual(
            affectation.statut,
            AffectationRegionale.Statut.ACTIVE,
        )
        full_clean.assert_called_once()
        sauvegarder.assert_called_once()

    def test_proposition_regionale_peut_etre_rejetee(self):
        affectation = AffectationRegionale(
            statut=AffectationRegionale.Statut.PROPOSEE,
        )

        with patch.object(AffectationRegionale, "save") as sauvegarder:
            resultat = affectation.rejeter("Région incorrecte")

        self.assertIs(resultat, affectation)
        self.assertEqual(
            affectation.statut,
            AffectationRegionale.Statut.REJETEE,
        )
        self.assertEqual(affectation.motif, "Région incorrecte")
        sauvegarder.assert_called_once()

    def test_affectation_non_proposee_ne_peut_pas_etre_rejetee(self):
        affectation = AffectationRegionale(
            statut=AffectationRegionale.Statut.ACTIVE,
        )

        with self.assertRaises(ValidationError):
            affectation.rejeter("Erreur")


class AlgorithmesAffectationsTests(SimpleTestCase):
    def test_normalisation_geographique(self):
        self.assertEqual(
            NormalisationGeographiqueService.normaliser(
                "Région des Hauts-Bassins"
            ),
            "haut bassin",
        )
        self.assertEqual(
            NormalisationGeographiqueService.normaliser("CENTRE-NORD"),
            "centre nord",
        )

    def test_score_exact_normalise(self):
        score = NormalisationGeographiqueService.score(
            "Région des Hauts-Bassins",
            "Hauts Bassins",
        )
        self.assertEqual(score, 1.0)

    def test_taille_lot_est_bornee(self):
        self.assertEqual(
            AffectationRegionaleService.valider_taille_lot(50),
            50,
        )

        with self.assertRaises(ValidationAffectationErreur):
            AffectationRegionaleService.valider_taille_lot(0)

        with self.assertRaises(ValidationAffectationErreur):
            AffectationRegionaleService.valider_taille_lot(1001)

    def test_compatibilite_genre_centre(self):
        self.assertTrue(
            AffectationCentreService._genre_compatible(
                "M",
                CentreImmersion.Genre.MASCULIN,
            )
        )
        self.assertFalse(
            AffectationCentreService._genre_compatible(
                "F",
                CentreImmersion.Genre.MASCULIN,
            )
        )
        self.assertTrue(
            AffectationCentreService._genre_compatible(
                "F",
                CentreImmersion.Genre.MIXTE,
            )
        )

    def test_compatibilite_public(self):
        self.assertTrue(
            AffectationCentreService._public_compatible(
                Immerge.TypeImmerge.BAC,
                ["BAC", "BEPC"],
            )
        )
        self.assertFalse(
            AffectationCentreService._public_compatible(
                Immerge.TypeImmerge.VOLONTAIRE,
                ["BAC", "BEPC"],
            )
        )
        self.assertTrue(
            AffectationCentreService._public_compatible(
                Immerge.TypeImmerge.VOLONTAIRE,
                [],
            )
        )

    def test_compatibilite_niveau_et_serie(self):
        profil = ProfilAffectation(
            immerge_id=1,
            origine_id=1,
            type_immerge=Immerge.TypeImmerge.BAC,
            sexe="F",
            niveau_examen="BAC",
            serie_filiere="D",
        )

        self.assertTrue(
            AffectationCentreService._niveau_compatible(
                profil,
                ["BAC_D"],
            )
        )
        self.assertFalse(
            AffectationCentreService._niveau_compatible(
                profil,
                ["BEPC"],
            )
        )


class SerializersAffectationsTests(SimpleTestCase):
    def test_serializer_lot_regional_valide(self):
        serializer = PropositionRegionaleLotInputSerializer(
            data={
                "session_id": 1,
                "nombre": 50,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["nombre"], 50)

    def test_serializer_lot_refuse_plus_de_mille(self):
        serializer = PropositionCentreLotInputSerializer(
            data={
                "session_id": 1,
                "region_id": 2,
                "nombre": 1001,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("nombre", serializer.errors)

    def test_serializer_validation_refuse_les_ids_dupliques(self):
        serializer = ValidationAffectationsLotInputSerializer(
            data={
                "affectation_ids": [1, 1, 2],
                "motif": "Lot vérifié",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("affectation_ids", serializer.errors)

    def test_serializer_rejet_exige_un_motif(self):
        serializer = RejetAffectationsLotInputSerializer(
            data={
                "affectation_ids": [1, 2],
                "motif": "   ",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("motif", serializer.errors)

    def test_serializer_centre_refuse_les_publics_dupliques(self):
        serializer = CentreImmersionInputSerializer(
            data={
                "region_id": 1,
                "code": "CENTRE-001",
                "nom": "Centre principal",
                "province": "Kadiogo",
                "ville": "Ouagadougou",
                "publics_acceptes": ["BAC", "BAC"],
                "niveaux_acceptes": ["BAC_D"],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("publics_acceptes", serializer.errors)


class TachesEtRoutesAffectationsTests(SimpleTestCase):
    def tearDown(self):
        cache.delete(
            ProgressionAffectationService.cle_progression(
                "test-affectations-tests"
            )
        )

    def test_progression_est_stockee_et_relue(self):
        task_id = "test-affectations-tests"

        ProgressionAffectationService.definir(
            task_id,
            operation="test",
            statut=ProgressionAffectationService.STATUT_EN_COURS,
            progression=35,
            total=20,
            traites=7,
            proposes=5,
            restants=13,
        )
        progression = ProgressionAffectationService.lire(task_id)

        self.assertEqual(progression["progression"], 35)
        self.assertEqual(progression["traites"], 7)
        self.assertEqual(progression["proposes"], 5)
        self.assertEqual(progression["restants"], 13)

    def test_routes_principales_sont_resolues(self):
        attentes = {
            "/api/affectations/regions/": "affectations:regions-immersion-list",
            "/api/affectations/centres/": "affectations:centres-immersion-list",
            "/api/affectations/affectations-regionales/": (
                "affectations:affectations-regionales-list"
            ),
            "/api/affectations/affectations-centres/": (
                "affectations:affectations-centres-list"
            ),
        }

        for chemin, nom_vue in attentes.items():
            with self.subTest(chemin=chemin):
                self.assertEqual(resolve(chemin).view_name, nom_vue)

    def test_reverse_route_regions(self):
        self.assertEqual(
            reverse("affectations:regions-immersion-list"),
            "/api/affectations/regions/",
        )

    def test_permissions_correspondent_aux_actions_metier(self):
        self.assertEqual(
            PermissionRegionImmersion.action_permission_map["create"],
            "creer_region",
        )
        self.assertEqual(
            PermissionCentreImmersion.action_permission_map[
                "verifier_capacite"
            ],
            "verifier_capacite_centre",
        )
        self.assertEqual(
            PermissionAffectationRegionale.action_permission_map[
                "proposer_lot"
            ],
            "proposer_affectation_regionale",
        )
        self.assertEqual(
            PermissionAffectationCentre.action_permission_map["valider_lot"],
            "valider_affectation_centre",
        )

    def test_api_refuse_un_utilisateur_non_authentifie(self):
        client = APIClient()
        reponse = client.get("/api/affectations/regions/")

        self.assertIn(reponse.status_code, {401, 403})
