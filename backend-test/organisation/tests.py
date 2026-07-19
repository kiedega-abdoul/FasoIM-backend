from datetime import date, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse
from rest_framework.test import APIClient

from accounts.models import Acteur
from affectations.models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)
from affectations.service import ProfilAffectation
from immerges.models import Immerge
from sessions_app.models import ParametreSession, SessionImmersion

from .models import (
    STATUTS_AFFECTATION_GROUPE_OUVERTS,
    STATUTS_ATTRIBUTION_LIT_OUVERTS,
    AffectationGroupe,
    AttributionLit,
    Dortoir,
    Groupe,
    Lit,
    RegleOrganisationCentre,
    Section,
)
from .permissions import (
    PermissionAffectationGroupe,
    PermissionAttributionLit,
    PermissionDortoir,
    PermissionGroupe,
    PermissionLit,
    PermissionRegleOrganisation,
    PermissionSection,
)
from .repository import (
    AffectationGroupeRepository,
    AttributionLitRepository,
    CandidatsOrganisationRepository,
)
from .serializers import (
    PropositionOrganisationLotInputSerializer,
    RegleOrganisationCentreInputSerializer,
)
from .service import (
    HebergementService,
    OrganisationCentreService,
    RegleOrganisationCentreService,
    ValidationOrganisationErreur,
    VisiteMedicaleOrganisationService,
)
from .tasks import (
    ProgressionOrganisationService,
    appliquer_resultats_medicaux_task,
    generer_sections_groupes_task,
    proposer_affectations_groupes_task,
    proposer_attributions_lits_task,
    reorganiser_aptes_sous_reserve_task,
)


class OrganisationFixtureMixin:
    """Fabrique le minimum nécessaire sans dupliquer les données personnelles."""

    mot_de_passe = "TestOrganisation-2026!"

    def creer_socle(
        self,
        *,
        hebergement_active=True,
        visite_medicale_active=True,
    ):
        self.acteur = Acteur.objects.create_superuser(
            username="admin-organisation",
            email="admin-organisation@fasoim.test",
            password=self.mot_de_passe,
            first_name="Admin",
            last_name="Organisation",
        )
        self.session = SessionImmersion.objects.create(
            nom="Session organisation 2026",
            annee=2026,
            numero_promotion=2,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=date(2026, 8, 1),
            date_fin=date(2026, 8, 31),
            statut=SessionImmersion.Statut.EN_PREPARATION,
        )
        self.parametres = ParametreSession.objects.create(
            session=self.session,
            hebergement_active=hebergement_active,
            visite_medicale_active=visite_medicale_active,
        )
        self.region = RegionImmersion.objects.create(
            code="CENTRE-ORG",
            nom="Centre organisation",
        )
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="CENTRE-ORG-001",
            nom="Centre FasoIM organisation",
            province="Kadiogo",
            ville="Ouagadougou",
            genre=CentreImmersion.Genre.MIXTE,
            publics_acceptes=[],
            niveaux_acceptes=[],
        )
        self.regle = RegleOrganisationCentre.objects.create(
            session=self.session,
            centre=self.centre,
            capacite_ouverte=500,
            seuil_division_sections=100,
            capacite_max_section=100,
            seuil_division_groupes=50,
            capacite_max_groupe=50,
            repartition_sections_groupes_automatique=True,
            attribution_lits_automatique=True,
            consignes_kits_a_apporter="Prévoir une tenue de sport.",
            consignes_repas="Respecter les heures de repas.",
            regles_discipline="Respect mutuel obligatoire.",
        )

    def creer_affectation_centre(self, numero, *, sexe="M"):
        immerge = Immerge.objects.create(
            session=self.session,
            type_immerge=Immerge.TypeImmerge.SELECTIONNE,
            origine_id=10_000 + numero,
            code_fasoim=f"IP2026SEL02{numero:05d}",
            statut=Immerge.Statut.AFFECTE_CENTRE,
        )
        affectation_regionale = AffectationRegionale.objects.create(
            immerge=immerge,
            session=self.session,
            region=self.region,
            statut=AffectationRegionale.Statut.ACTIVE,
            affecte_par=self.acteur,
        )
        affectation_centre = AffectationCentre.objects.create(
            immerge=immerge,
            session=self.session,
            affectation_regionale=affectation_regionale,
            centre=self.centre,
            statut=AffectationCentre.Statut.ACTIVE,
            affecte_par=self.acteur,
        )
        affectation_centre.sexe_test = sexe
        return affectation_centre

    def creer_section_groupe(
        self,
        *,
        code_section="SEC-01",
        code_groupe="SEC-01-G01",
        capacite_section=50,
        capacite_groupe=50,
    ):
        section = Section.objects.create(
            session=self.session,
            centre=self.centre,
            nom=code_section,
            code=code_section,
            capacite_max=capacite_section,
        )
        groupe = Groupe.objects.create(
            section=section,
            nom=code_groupe,
            code=code_groupe,
            capacite_max=capacite_groupe,
        )
        return section, groupe

    def creer_dortoir_lit(
        self,
        *,
        nom,
        sexe,
        numero_lit,
        capacite=10,
    ):
        dortoir = Dortoir.objects.create(
            centre=self.centre,
            nom=nom,
            capacite=capacite,
            sexe_dortoir=sexe,
        )
        lit = Lit.objects.create(
            dortoir=dortoir,
            numero_lit=numero_lit,
        )
        return dortoir, lit


class ModelesOrganisationTests(OrganisationFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()

    def test_statuts_ouverts_reservent_groupes_et_lits(self):
        self.assertEqual(
            set(STATUTS_AFFECTATION_GROUPE_OUVERTS),
            {
                AffectationGroupe.Statut.PROPOSEE,
                AffectationGroupe.Statut.ACTIVE,
                AffectationGroupe.Statut.A_REORGANISER,
            },
        )
        self.assertEqual(
            set(STATUTS_ATTRIBUTION_LIT_OUVERTS),
            {
                AttributionLit.Statut.PROPOSEE,
                AttributionLit.Statut.ACTIVE,
                AttributionLit.Statut.A_REORGANISER,
            },
        )

    def test_regle_reflete_les_modules_actives_dans_la_session(self):
        self.assertTrue(self.regle.hebergement_active)
        self.assertTrue(self.regle.visite_medicale_active)
        self.assertIn("tenue de sport", self.regle.consignes_kits_a_apporter)
        self.assertIn("heures de repas", self.regle.consignes_repas)

    def test_regle_refuse_un_groupe_plus_grand_que_la_section(self):
        self.regle.capacite_max_section = 30
        self.regle.capacite_max_groupe = 40

        with self.assertRaises(ValidationError) as contexte:
            self.regle.full_clean()

        self.assertIn(
            "capacite_max_groupe",
            contexte.exception.message_dict,
        )

    def test_groupe_refuse_une_capacite_superieure_a_sa_section(self):
        section = Section.objects.create(
            session=self.session,
            centre=self.centre,
            nom="Section petite",
            code="SEC-P",
            capacite_max=20,
        )
        groupe = Groupe(
            section=section,
            nom="Groupe trop grand",
            code="GRP-TG",
            capacite_max=30,
        )

        with self.assertRaises(ValidationError) as contexte:
            groupe.full_clean()

        self.assertIn("capacite_max", contexte.exception.message_dict)

    def test_suppression_groupe_refuse_une_affectation_ouverte(self):
        affectation_centre = self.creer_affectation_centre(1)
        _, groupe = self.creer_section_groupe()
        AffectationGroupe.objects.create(
            affectation_centre=affectation_centre,
            groupe=groupe,
            statut=AffectationGroupe.Statut.ACTIVE,
            affecte_par=self.acteur,
        )

        with self.assertRaises(ValidationError):
            groupe.supprimer_logiquement()

    def test_suppression_lit_refuse_une_attribution_ouverte(self):
        affectation_centre = self.creer_affectation_centre(1)
        _, lit = self.creer_dortoir_lit(
            nom="Dortoir masculin",
            sexe=Dortoir.SexeDortoir.MASCULIN,
            numero_lit="M-001",
        )
        AttributionLit.objects.create(
            affectation_centre=affectation_centre,
            lit=lit,
            statut=AttributionLit.Statut.ACTIVE,
            attribue_par=self.acteur,
        )

        with self.assertRaises(ValidationError):
            lit.supprimer_logiquement()


class AlgorithmesOrganisationTests(SimpleTestCase):
    def setUp(self):
        self.regle = RegleOrganisationCentre(
            seuil_division_sections=100,
            capacite_max_section=100,
            seuil_division_groupes=50,
            capacite_max_groupe=50,
        )

    def test_repartition_equilibree(self):
        self.assertEqual(
            OrganisationCentreService._repartir_equitablement(10, 3),
            [4, 3, 3],
        )
        self.assertEqual(
            OrganisationCentreService._repartir_equitablement(2, 4),
            [1, 1, 0, 0],
        )

    def test_effectif_faible_produit_une_section_et_un_groupe(self):
        self.assertEqual(
            OrganisationCentreService._nombre_sections(30, self.regle),
            1,
        )
        self.assertEqual(
            OrganisationCentreService._nombre_groupes(30, self.regle),
            1,
        )

    def test_capacite_force_la_division_meme_avant_le_seuil(self):
        self.regle.seuil_division_sections = 200
        self.regle.capacite_max_section = 50
        self.regle.seuil_division_groupes = 100
        self.regle.capacite_max_groupe = 20

        self.assertEqual(
            OrganisationCentreService._nombre_sections(120, self.regle),
            3,
        )
        self.assertEqual(
            OrganisationCentreService._nombre_groupes(50, self.regle),
            3,
        )

    def test_taille_lot_est_bornee(self):
        self.assertEqual(
            OrganisationCentreService.valider_taille_lot(5000),
            5000,
        )

        with self.assertRaises(ValidationOrganisationErreur):
            OrganisationCentreService.valider_taille_lot(0)

        with self.assertRaises(ValidationOrganisationErreur):
            OrganisationCentreService.valider_taille_lot(5001)

    def test_normalisation_du_sexe_pour_les_dortoirs(self):
        self.assertEqual(
            HebergementService._sexe_dortoir("M"),
            Dortoir.SexeDortoir.MASCULIN,
        )
        self.assertEqual(
            HebergementService._sexe_dortoir("FEMININ"),
            Dortoir.SexeDortoir.FEMININ,
        )
        self.assertIsNone(HebergementService._sexe_dortoir("NON_PRECISE"))

    def test_serializer_lot_refuse_plus_de_cinq_mille(self):
        serializer = PropositionOrganisationLotInputSerializer(
            data={
                "session_id": 1,
                "centre_id": 1,
                "nombre": 5001,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("nombre", serializer.errors)

    def test_serializer_regle_refuse_capacite_incoherente(self):
        serializer = RegleOrganisationCentreInputSerializer(
            data={
                "session_id": 1,
                "centre_id": 1,
                "capacite_ouverte": 100,
                "seuil_division_sections": 100,
                "capacite_max_section": 30,
                "seuil_division_groupes": 20,
                "capacite_max_groupe": 40,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("capacite_max_groupe", serializer.errors)


class ServicesOrganisationTests(OrganisationFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()

    def test_generation_effectif_faible_cree_une_section_et_un_groupe(self):
        for numero in range(1, 4):
            self.creer_affectation_centre(numero)

        resultat = OrganisationCentreService.generer_sections_groupes(
            session_id=self.session.id,
            centre_id=self.centre.id,
        )

        self.assertEqual(resultat.crees, 2)
        self.assertEqual(
            Section.objects.filter(
                session=self.session,
                centre=self.centre,
                deleted_at__isnull=True,
            ).count(),
            1,
        )
        self.assertEqual(
            Groupe.objects.filter(
                section__session=self.session,
                section__centre=self.centre,
                deleted_at__isnull=True,
            ).count(),
            1,
        )
        self.regle.refresh_from_db()
        self.assertEqual(
            self.regle.statut,
            RegleOrganisationCentre.Statut.EN_COURS,
        )

    def test_generation_ne_duplique_pas_les_structures_existantes(self):
        self.creer_affectation_centre(1)

        premier = OrganisationCentreService.generer_sections_groupes(
            session_id=self.session.id,
            centre_id=self.centre.id,
        )
        second = OrganisationCentreService.generer_sections_groupes(
            session_id=self.session.id,
            centre_id=self.centre.id,
        )

        self.assertEqual(premier.crees, 2)
        self.assertEqual(second.crees, 0)
        self.assertEqual(Section.objects.count(), 1)
        self.assertEqual(Groupe.objects.count(), 1)

    def test_propositions_groupes_sont_equilibrees_sans_critere_de_profil(self):
        affectations = [
            self.creer_affectation_centre(numero)
            for numero in range(1, 5)
        ]
        section = Section.objects.create(
            session=self.session,
            centre=self.centre,
            nom="Section équilibre",
            code="SEC-EQ",
            capacite_max=4,
        )
        groupe_1 = Groupe.objects.create(
            section=section,
            nom="Groupe 1",
            code="SEC-EQ-G01",
            capacite_max=2,
        )
        groupe_2 = Groupe.objects.create(
            section=section,
            nom="Groupe 2",
            code="SEC-EQ-G02",
            capacite_max=2,
        )

        resultat = OrganisationCentreService.proposer_affectations_groupes(
            session_id=self.session.id,
            centre_id=self.centre.id,
            nombre=4,
            acteur=self.acteur,
        )

        self.assertEqual(resultat.crees, 4)
        occupations = {
            groupe_1.id: AffectationGroupe.objects.filter(
                groupe=groupe_1,
                statut=AffectationGroupe.Statut.PROPOSEE,
            ).count(),
            groupe_2.id: AffectationGroupe.objects.filter(
                groupe=groupe_2,
                statut=AffectationGroupe.Statut.PROPOSEE,
            ).count(),
        }
        self.assertEqual(occupations[groupe_1.id], 2)
        self.assertEqual(occupations[groupe_2.id], 2)
        self.assertEqual(
            set(
                AffectationGroupe.objects.values_list(
                    "affectation_centre_id",
                    flat=True,
                )
            ),
            {affectation.id for affectation in affectations},
        )

    def test_validation_en_lot_active_les_propositions_groupes(self):
        affectation_centre = self.creer_affectation_centre(1)
        _, groupe = self.creer_section_groupe()
        proposition = AffectationGroupe.objects.create(
            affectation_centre=affectation_centre,
            groupe=groupe,
            statut=AffectationGroupe.Statut.PROPOSEE,
        )

        OrganisationCentreService.valider_affectations_groupes(
            [proposition.id],
            acteur=self.acteur,
        )

        proposition.refresh_from_db()
        self.assertEqual(
            proposition.statut,
            AffectationGroupe.Statut.ACTIVE,
        )
        self.assertEqual(proposition.affecte_par, self.acteur)

    def test_attribution_lits_respecte_uniquement_le_sexe_du_dortoir(self):
        affectation_m = self.creer_affectation_centre(1, sexe="M")
        affectation_f = self.creer_affectation_centre(2, sexe="F")
        dortoir_m, lit_m = self.creer_dortoir_lit(
            nom="Dortoir hommes",
            sexe=Dortoir.SexeDortoir.MASCULIN,
            numero_lit="M-001",
        )
        dortoir_f, lit_f = self.creer_dortoir_lit(
            nom="Dortoir femmes",
            sexe=Dortoir.SexeDortoir.FEMININ,
            numero_lit="F-001",
        )
        profils = {
            affectation_m.immerge_id: ProfilAffectation(
                immerge_id=affectation_m.immerge_id,
                origine_id=affectation_m.immerge.origine_id,
                type_immerge=affectation_m.immerge.type_immerge,
                sexe="M",
            ),
            affectation_f.immerge_id: ProfilAffectation(
                immerge_id=affectation_f.immerge_id,
                origine_id=affectation_f.immerge.origine_id,
                type_immerge=affectation_f.immerge.type_immerge,
                sexe="F",
            ),
        }

        with patch(
            "organisation.service.ProfilAffectationService.construire_profils",
            return_value=(profils, []),
        ):
            resultat = HebergementService.proposer_attributions_lits(
                session_id=self.session.id,
                centre_id=self.centre.id,
                nombre=2,
                acteur=self.acteur,
            )

        self.assertEqual(resultat.crees, 2)
        self.assertTrue(
            AttributionLit.objects.filter(
                affectation_centre=affectation_m,
                lit=lit_m,
            ).exists()
        )
        self.assertTrue(
            AttributionLit.objects.filter(
                affectation_centre=affectation_f,
                lit=lit_f,
            ).exists()
        )
        self.assertNotEqual(dortoir_m.sexe_dortoir, dortoir_f.sexe_dortoir)

    def _creer_organisation_active(self):
        affectation_centre = self.creer_affectation_centre(1)
        _, groupe = self.creer_section_groupe()
        _, lit = self.creer_dortoir_lit(
            nom="Dortoir médical",
            sexe=Dortoir.SexeDortoir.MASCULIN,
            numero_lit="MED-001",
        )
        affectation_groupe = AffectationGroupe.objects.create(
            affectation_centre=affectation_centre,
            groupe=groupe,
            statut=AffectationGroupe.Statut.ACTIVE,
            affecte_par=self.acteur,
        )
        attribution_lit = AttributionLit.objects.create(
            affectation_centre=affectation_centre,
            lit=lit,
            statut=AttributionLit.Statut.ACTIVE,
            attribue_par=self.acteur,
        )
        return affectation_centre, affectation_groupe, attribution_lit

    def test_resultat_apte_conserve_toute_l_organisation(self):
        (
            affectation_centre,
            affectation_groupe,
            attribution_lit,
        ) = self._creer_organisation_active()

        resultat = VisiteMedicaleOrganisationService.appliquer_resultat(
            affectation_centre_id=affectation_centre.id,
            resultat="APTE",
        )

        affectation_groupe.refresh_from_db()
        attribution_lit.refresh_from_db()
        self.assertEqual(resultat["action"], "ORGANISATION_CONSERVEE")
        self.assertEqual(
            affectation_groupe.statut,
            AffectationGroupe.Statut.ACTIVE,
        )
        self.assertEqual(
            attribution_lit.statut,
            AttributionLit.Statut.ACTIVE,
        )

    def test_apte_sous_reserve_est_marque_a_reorganiser(self):
        (
            affectation_centre,
            affectation_groupe,
            attribution_lit,
        ) = self._creer_organisation_active()

        resultat = VisiteMedicaleOrganisationService.appliquer_resultat(
            affectation_centre_id=affectation_centre.id,
            resultat="APTE_SOUS_RESERVE",
            observations="Lit proche de l'infirmerie.",
        )

        affectation_groupe.refresh_from_db()
        attribution_lit.refresh_from_db()
        self.assertEqual(resultat["action"], "A_REORGANISER")
        self.assertEqual(
            affectation_groupe.statut,
            AffectationGroupe.Statut.A_REORGANISER,
        )
        self.assertEqual(
            attribution_lit.statut,
            AttributionLit.Statut.A_REORGANISER,
        )

    def test_inapte_est_retire_de_l_organisation(self):
        (
            affectation_centre,
            affectation_groupe,
            attribution_lit,
        ) = self._creer_organisation_active()

        resultat = VisiteMedicaleOrganisationService.appliquer_resultat(
            affectation_centre_id=affectation_centre.id,
            resultat="INAPTE_TEMPORAIRE",
        )

        affectation_groupe.refresh_from_db()
        attribution_lit.refresh_from_db()
        self.assertEqual(
            resultat["action"],
            "RETIRE_DE_L_ORGANISATION",
        )
        self.assertEqual(
            affectation_groupe.statut,
            AffectationGroupe.Statut.ANNULEE,
        )
        self.assertIsNotNone(affectation_groupe.deleted_at)
        self.assertEqual(
            attribution_lit.statut,
            AttributionLit.Statut.LIBEREE,
        )
        self.assertIsNotNone(attribution_lit.date_liberation)
        self.assertIsNotNone(attribution_lit.deleted_at)

    def test_validation_organisation_reussit_sans_hebergement(self):
        self.parametres.hebergement_active = False
        self.parametres.save()

        affectation_centre = self.creer_affectation_centre(1)
        _, groupe = self.creer_section_groupe()
        AffectationGroupe.objects.create(
            affectation_centre=affectation_centre,
            groupe=groupe,
            statut=AffectationGroupe.Statut.ACTIVE,
            affecte_par=self.acteur,
        )

        regle = RegleOrganisationCentreService.valider_organisation(
            session_id=self.session.id,
            centre_id=self.centre.id,
            acteur=self.acteur,
        )

        self.assertEqual(
            regle.statut,
            RegleOrganisationCentre.Statut.VALIDEE,
        )
        self.assertEqual(regle.validee_par, self.acteur)

    def test_validation_refuse_une_proposition_non_validee(self):
        self.parametres.hebergement_active = False
        self.parametres.save()

        affectation_centre = self.creer_affectation_centre(1)
        _, groupe = self.creer_section_groupe()
        AffectationGroupe.objects.create(
            affectation_centre=affectation_centre,
            groupe=groupe,
            statut=AffectationGroupe.Statut.PROPOSEE,
        )

        with self.assertRaises(ValidationOrganisationErreur):
            RegleOrganisationCentreService.valider_organisation(
                session_id=self.session.id,
                centre_id=self.centre.id,
                acteur=self.acteur,
            )

    def test_repository_ne_retient_que_les_candidats_sans_groupe(self):
        affectation_1 = self.creer_affectation_centre(1)
        affectation_2 = self.creer_affectation_centre(2)
        _, groupe = self.creer_section_groupe()
        AffectationGroupe.objects.create(
            affectation_centre=affectation_1,
            groupe=groupe,
            statut=AffectationGroupe.Statut.ACTIVE,
        )

        candidats = list(
            CandidatsOrganisationRepository.candidats_groupes(
                session_id=self.session.id,
                centre_id=self.centre.id,
            )
        )

        self.assertEqual(
            [candidat.id for candidat in candidats],
            [affectation_2.id],
        )
        self.assertEqual(
            AffectationGroupeRepository.compter_ouvertes_centre(
                session_id=self.session.id,
                centre_id=self.centre.id,
            ),
            1,
        )
        self.assertEqual(
            AttributionLitRepository.compter_ouvertes_centre(
                session_id=self.session.id,
                centre_id=self.centre.id,
            ),
            0,
        )


class TachesPermissionsEtRoutesOrganisationTests(SimpleTestCase):
    task_id = "test-organisation-tests"

    def tearDown(self):
        cache.delete(
            ProgressionOrganisationService.cle_progression(
                self.task_id
            )
        )

    def test_progression_est_stockee_et_relue(self):
        ProgressionOrganisationService.definir(
            self.task_id,
            operation="test",
            statut=ProgressionOrganisationService.STATUT_EN_COURS,
            progression=45,
            total=20,
            traites=9,
            crees=7,
            restants=11,
        )

        progression = ProgressionOrganisationService.lire(self.task_id)

        self.assertEqual(progression["progression"], 45)
        self.assertEqual(progression["traites"], 9)
        self.assertEqual(progression["crees"], 7)
        self.assertEqual(progression["restants"], 11)

    def test_noms_des_taches_celery_sont_stables(self):
        attentes = {
            generer_sections_groupes_task.name,
            proposer_affectations_groupes_task.name,
            proposer_attributions_lits_task.name,
            appliquer_resultats_medicaux_task.name,
            reorganiser_aptes_sous_reserve_task.name,
        }

        self.assertEqual(
            attentes,
            {
                "organisation.tasks.generer_sections_groupes_task",
                "organisation.tasks.proposer_affectations_groupes_task",
                "organisation.tasks.proposer_attributions_lits_task",
                "organisation.tasks.appliquer_resultats_medicaux_task",
                "organisation.tasks.reorganiser_aptes_sous_reserve_task",
            },
        )

    def test_routes_principales_sont_resolues(self):
        attentes = {
            "/api/organisation/regles-centres/": (
                "organisation:regles-centres-list"
            ),
            "/api/organisation/sections/": "organisation:sections-list",
            "/api/organisation/groupes/": "organisation:groupes-list",
            "/api/organisation/affectations-groupes/": (
                "organisation:affectations-groupes-list"
            ),
            "/api/organisation/dortoirs/": "organisation:dortoirs-list",
            "/api/organisation/lits/": "organisation:lits-list",
            "/api/organisation/attributions-lits/": (
                "organisation:attributions-lits-list"
            ),
        }

        for chemin, nom_vue in attentes.items():
            with self.subTest(chemin=chemin):
                self.assertEqual(resolve(chemin).view_name, nom_vue)

    def test_reverse_route_regles_centres(self):
        self.assertEqual(
            reverse("organisation:regles-centres-list"),
            "/api/organisation/regles-centres/",
        )

    def test_permissions_correspondent_aux_actions_metier(self):
        self.assertEqual(
            PermissionRegleOrganisation.action_permission_map[
                "generer_structures"
            ],
            "generer_sections_groupes",
        )
        self.assertEqual(
            PermissionSection.action_permission_map["create"],
            "creer_section",
        )
        self.assertEqual(
            PermissionGroupe.action_permission_map["destroy"],
            "supprimer_groupe",
        )
        self.assertEqual(
            PermissionAffectationGroupe.action_permission_map[
                "proposer_lot"
            ],
            "affecter_immerge_groupe",
        )
        self.assertEqual(
            PermissionDortoir.action_permission_map[
                "mettre_hors_service"
            ],
            "mettre_dortoir_hors_service",
        )
        self.assertEqual(
            PermissionLit.action_permission_map["reactiver"],
            "reactiver_lit",
        )
        self.assertEqual(
            PermissionAttributionLit.action_permission_map["liberer"],
            "liberer_lit",
        )

    def test_api_refuse_un_utilisateur_non_authentifie(self):
        client = APIClient()
        reponse = client.get(
            "/api/organisation/regles-centres/",
            {"session_id": 1},
        )

        self.assertIn(reponse.status_code, {401, 403})
