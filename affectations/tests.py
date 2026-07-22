from datetime import date
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse
from rest_framework.test import APIClient

from immerges.models import Immerge
from sessions_app.models import ParametreSession, SessionImmersion
from organisation.models import Dortoir, Lit, RegleOrganisationCentre

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
    AffectationRegionaleRepository,
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
    PerimetreCentresSessionService,
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

    def test_centre_mixte_respecte_la_capacite_reelle_des_lits_par_sexe(self):
        session = SessionImmersion.objects.create(
            nom="Session capacité par sexe",
            annee=2026,
            numero_promotion=97,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=date(2026, 7, 1),
            date_fin=date(2026, 7, 31),
            statut=SessionImmersion.Statut.EN_PREPARATION,
        )
        ParametreSession.objects.create(
            session=session,
            hebergement_active=True,
            centres_accueil=[{"centre_id": self.centre.id}],
        )
        dortoir_h = Dortoir.objects.create(
            centre=self.centre, nom="Hommes",
            sexe_dortoir=Dortoir.SexeDortoir.MASCULIN, capacite=1,
        )
        dortoir_f = Dortoir.objects.create(
            centre=self.centre, nom="Femmes",
            sexe_dortoir=Dortoir.SexeDortoir.FEMININ, capacite=2,
        )
        Lit.objects.create(dortoir=dortoir_h, numero_lit="H1")
        Lit.objects.create(dortoir=dortoir_f, numero_lit="F1")
        Lit.objects.create(dortoir=dortoir_f, numero_lit="F2")

        capacites = AffectationCentreService._capacites_sexe_centres(
            session_id=session.id,
            centres=[{"id": self.centre.id}],
        )

        self.assertEqual(capacites[self.centre.id]["M"]["disponible"], 1)
        self.assertEqual(capacites[self.centre.id]["F"]["disponible"], 2)

    def test_perimetre_session_ne_duplique_pas_les_regions_par_centre(self):
        centre_secondaire = CentreImmersion.objects.create(
            region=self.region,
            code="CENTRE-DOUBLON-002",
            nom="Centre secondaire même région",
            province="Kadiogo",
            ville="Ouagadougou",
        )
        autre_region = RegionImmersion.objects.create(
            code="AUTRE-REGION",
            nom="Autre région",
        )
        centre_autre_region = CentreImmersion.objects.create(
            region=autre_region,
            code="AUTRE-REGION-001",
            nom="Centre autre région",
            province="Autre",
            ville="Autre",
        )
        session = SessionImmersion.objects.create(
            nom="Session périmètre régions uniques 2026",
            annee=2026,
            numero_promotion=98,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=date(2026, 7, 1),
            date_fin=date(2026, 7, 31),
            statut=SessionImmersion.Statut.EN_PREPARATION,
        )
        ParametreSession.objects.create(
            session=session,
            centres_accueil=[
                {"centre_id": self.centre.id},
                {"centre_id": centre_secondaire.id},
                {"centre_id": centre_autre_region.id},
            ],
        )

        centre_ids, region_ids = PerimetreCentresSessionService.region_ids(session.id)

        self.assertCountEqual(
            centre_ids,
            [self.centre.id, centre_secondaire.id, centre_autre_region.id],
        )
        self.assertEqual(region_ids, sorted([self.region.id, autre_region.id]))

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
        ParametreSession.objects.create(
            session=session,
            centres_accueil=[
                {
                    "centre_id": self.centre.id,
                    "centre_code": self.centre.code,
                    "centre_nom": self.centre.nom,
                },
                {
                    "centre_id": centre_secondaire.id,
                    "centre_code": centre_secondaire.code,
                    "centre_nom": centre_secondaire.nom,
                },
            ],
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

    def test_capacites_distinguent_propositions_et_affectations_validees(self):
        session = SessionImmersion.objects.create(
            nom="Session distinction capacités 2026",
            annee=2026,
            numero_promotion=100,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=date(2026, 9, 1),
            date_fin=date(2026, 9, 30),
            statut=SessionImmersion.Statut.EN_PREPARATION,
        )
        RegleOrganisationCentre.objects.create(
            session=session,
            centre=self.centre,
            capacite_ouverte=10,
            seuil_division_sections=10,
            capacite_max_section=10,
            seuil_division_groupes=5,
            capacite_max_groupe=5,
            statut=RegleOrganisationCentre.Statut.VALIDEE,
        )
        ParametreSession.objects.create(
            session=session,
            centres_accueil=[
                {
                    "centre_id": self.centre.id,
                    "centre_code": self.centre.code,
                    "centre_nom": self.centre.nom,
                }
            ],
        )
        source = Immerge.objects.create(
            session=session,
            type_immerge=Immerge.TypeImmerge.BAC,
            origine_id=1,
            code_fasoim="IP2026BAC9900001",
            qr_code="qr-capacite-1",
            statut=Immerge.Statut.CODE_GENERE,
        )
        AffectationRegionale.objects.create(
            immerge=source,
            session=session,
            region=self.region,
            statut=AffectationRegionale.Statut.PROPOSEE,
        )
        source_validee = Immerge.objects.create(
            session=session,
            type_immerge=Immerge.TypeImmerge.BAC,
            origine_id=2,
            code_fasoim="IP2026BAC9900002",
            qr_code="qr-capacite-2",
            statut=Immerge.Statut.AFFECTE_REGION,
        )
        AffectationRegionale.objects.create(
            immerge=source_validee,
            session=session,
            region=self.region,
            statut=AffectationRegionale.Statut.ACTIVE,
        )

        rapport = CapaciteAffectationService.rapport_regions(session.id)
        region = rapport["regions"][0]

        self.assertEqual(rapport["session"]["type_session"], session.type_session)
        self.assertEqual(rapport["session"]["public_cible"], session.public_cible)
        self.assertEqual(rapport["propositions_en_attente_total"], 1)
        self.assertEqual(rapport["affectations_validees_total"], 1)
        self.assertEqual(rapport["places_reservees_total"], 2)
        self.assertEqual(rapport["occupation_totale"], 1)
        self.assertEqual(rapport["disponible_total"], 8)
        self.assertEqual(region["propositions_en_attente"], 1)
        self.assertEqual(region["affectations_validees"], 1)
        self.assertEqual(region["places_reservees"], 2)
        self.assertEqual(region["occupation"], 1)

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

        self.assertEqual(
            AffectationRegionaleService.valider_taille_lot(10000),
            10000,
        )

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

    def test_libelles_generiques_bac_acceptent_toutes_les_series(self):
        profil = ProfilAffectation(
            immerge_id=1,
            origine_id=1,
            type_immerge=Immerge.TypeImmerge.BAC,
            sexe="F",
            niveau_examen="BAC",
            serie_filiere="A4",
        )

        for libelle in (
            "BAC",
            "Tous type de BAC",
            "Tous les types de BAC",
            "Toutes les séries de BAC",
        ):
            with self.subTest(libelle=libelle):
                self.assertTrue(
                    AffectationCentreService._niveau_compatible(
                        profil,
                        [libelle],
                    )
                )

    def test_libelle_generique_d_un_autre_niveau_reste_incompatible(self):
        profil = ProfilAffectation(
            immerge_id=1,
            origine_id=1,
            type_immerge=Immerge.TypeImmerge.BAC,
            sexe="F",
            niveau_examen="BAC",
            serie_filiere="D",
        )

        self.assertFalse(
            AffectationCentreService._niveau_compatible(
                profil,
                ["Tous type de BEPC"],
            )
        )


class ReglesPropositionsRegionalesTests(SimpleTestCase):

    def test_correspondance_faible_n_est_pas_proposee_sans_choix_explicite(self):
        profil = ProfilAffectation(
            immerge_id=1,
            origine_id=1,
            type_immerge=Immerge.TypeImmerge.BAC,
            region_reference="Nord",
        )
        regions = [{"id": 1, "nom": "Plateau central", "code": "PLATEAU_CENTRAL"}]
        capacites = {1: {"disponible": 100}}

        region, score, mode = AffectationRegionaleService._choisir_region(
            profil=profil,
            regions=regions,
            capacites=capacites,
            forcer_reliquat=False,
        )

        self.assertIsNone(region)
        self.assertLess(score, AffectationRegionaleService.SEUIL_CORRESPONDANCE_ASSOUPLIE)
        self.assertEqual(mode, "correspondance_insuffisante")

    def test_correspondance_faible_est_proposee_seulement_si_acteur_force_reliquat(self):
        profil = ProfilAffectation(
            immerge_id=1,
            origine_id=1,
            type_immerge=Immerge.TypeImmerge.BAC,
            region_reference="Nord",
        )
        regions = [{"id": 1, "nom": "Plateau central", "code": "PLATEAU_CENTRAL"}]
        capacites = {1: {"disponible": 100}}

        region, score, mode = AffectationRegionaleService._choisir_region(
            profil=profil,
            regions=regions,
            capacites=capacites,
            forcer_reliquat=True,
        )

        self.assertEqual(region["id"], 1)
        self.assertLess(score, AffectationRegionaleService.SEUIL_CORRESPONDANCE_ASSOUPLIE)
        self.assertEqual(mode, "correspondance_assouplie")

    def test_nouveau_lot_refuse_si_des_propositions_sont_en_attente(self):
        with patch.object(
            AffectationRegionaleRepository,
            "compter_propositions_en_attente",
            return_value=3,
        ):
            with self.assertRaises(ValidationAffectationErreur) as contexte:
                AffectationRegionaleService.verifier_aucune_proposition_en_attente(1)

        self.assertIn("propositions", contexte.exception.message_dict)


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


    def test_serializer_lot_regional_accepte_dix_mille(self):
        serializer = PropositionRegionaleLotInputSerializer(
            data={
                "session_id": 1,
                "nombre": 10000,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["nombre"], 10000)

    def test_serializer_lot_centre_accepte_dix_mille(self):
        serializer = PropositionCentreLotInputSerializer(
            data={
                "session_id": 1,
                "region_id": 2,
                "nombre": 10000,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["nombre"], 10000)

    def test_serializer_lot_centre_refuse_zero(self):
        serializer = PropositionCentreLotInputSerializer(
            data={
                "session_id": 1,
                "region_id": 2,
                "nombre": 0,
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

    def test_serializer_validation_accepte_dix_mille_ids(self):
        serializer = ValidationAffectationsLotInputSerializer(
            data={
                "affectation_ids": list(range(1, 10001)),
                "motif": "Validation nationale",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(len(serializer.validated_data["affectation_ids"]), 10000)

    def test_serializer_validation_refuse_plus_de_dix_mille_ids(self):
        serializer = ValidationAffectationsLotInputSerializer(
            data={
                "affectation_ids": list(range(1, 10002)),
                "motif": "Lot trop volumineux",
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


class CapacitesRegionalesCompatiblesTests(SimpleTestCase):
    def setUp(self):
        self.regions = [
            {"id": 1, "nom": "Région féminine", "code": "FEM"},
            {"id": 2, "nom": "Région mixte", "code": "MIX"},
        ]
        self.centres_par_region = {
            1: [
                {
                    "id": 10,
                    "region_id": 1,
                    "genre": CentreImmersion.Genre.FEMININ,
                    "publics_acceptes": [Immerge.TypeImmerge.BAC],
                }
            ],
            2: [
                {
                    "id": 20,
                    "region_id": 2,
                    "genre": CentreImmersion.Genre.MIXTE,
                    "publics_acceptes": [Immerge.TypeImmerge.BAC],
                }
            ],
        }
        self.capacites = {
            10: {"disponible": 100, "capacite_totale": 100},
            20: {"disponible": 50, "capacite_totale": 50},
        }

    def test_un_homme_ne_consomme_pas_une_place_d_un_centre_feminin(self):
        profil = ProfilAffectation(
            immerge_id=1,
            origine_id=1,
            type_immerge=Immerge.TypeImmerge.BAC,
            sexe="M",
        )

        resultat = AffectationRegionaleService._capacites_regionales_compatibles(
            profil=profil,
            regions=self.regions,
            centres_par_region=self.centres_par_region,
            capacites_centres=self.capacites,
        )

        self.assertEqual(resultat[1]["disponible"], 0)
        self.assertEqual(resultat[2]["disponible"], 50)

    def test_une_femme_peut_utiliser_un_centre_feminin_ou_mixte(self):
        profil = ProfilAffectation(
            immerge_id=1,
            origine_id=1,
            type_immerge=Immerge.TypeImmerge.BAC,
            sexe="F",
        )

        resultat = AffectationRegionaleService._capacites_regionales_compatibles(
            profil=profil,
            regions=self.regions,
            centres_par_region=self.centres_par_region,
            capacites_centres=self.capacites,
        )

        self.assertEqual(resultat[1]["disponible"], 100)
        self.assertEqual(resultat[2]["disponible"], 50)

    def test_un_public_non_accepte_ne_consomme_aucune_place(self):
        profil = ProfilAffectation(
            immerge_id=1,
            origine_id=1,
            type_immerge=Immerge.TypeImmerge.CONCOURS,
            sexe="F",
        )

        resultat = AffectationRegionaleService._capacites_regionales_compatibles(
            profil=profil,
            regions=self.regions,
            centres_par_region=self.centres_par_region,
            capacites_centres=self.capacites,
        )

        self.assertEqual(resultat[1]["disponible"], 0)
        self.assertEqual(resultat[2]["disponible"], 0)
