from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase, override_settings
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
from organisation.models import (
    AffectationGroupe,
    Groupe,
    Section,
)
from sessions_app.models import (
    ParametreSession,
    SessionImmersion,
)

from .models import (
    Evaluation,
    ModuleActivite,
    Note,
    Presence,
    Seance,
)
from .permissions import (
    PermissionEvaluation,
    PermissionModuleActivite,
    PermissionNote,
    PermissionOperationActivite,
    PermissionPresence,
    PermissionSeance,
)
from .repository import (
    CandidatActiviteRepository,
    EvaluationRepository,
    ModuleActiviteRepository,
    NoteRepository,
    PresenceRepository,
    SeanceRepository,
)
from .serializers import (
    EvaluationCreateSerializer,
    FiltreSeanceSerializer,
    LigneNoteMasseSerializer,
    NoteCreateSerializer,
    PresenceCreateSerializer,
    SaisiePresencesMasseSerializer,
    SeanceCreateSerializer,
)
from .service import (
    ActiviteService,
    EvaluationService,
    NoteService,
    PresenceService,
    SeanceService,
    ValidationActiviteErreur,
)
from .tasks import (
    ProgressionActivitesService,
    ouvrir_et_preparer_feuille_presence_task,
    saisir_notes_masse_task,
    saisir_presences_masse_task,
    valider_resultats_masse_task,
)


CACHE_TEST = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends.locmem.LocMemCache"
        ),
        "LOCATION": "tests-activites",
    }
}


class ActivitesFixtureMixin:
    mot_de_passe = "Test-Activites-2026!"

    def creer_socle(
        self,
        *,
        activites_active=True,
        evaluation_active=True,
        visite_medicale_active=False,
    ):
        self.acteur = Acteur.objects.create_superuser(
            username="admin-activites",
            email="admin-activites@fasoim.test",
            password=self.mot_de_passe,
            first_name="Admin",
            last_name="Activites",
        )
        self.formateur = Acteur.objects.create_user(
            username="formateur-activites",
            email="formateur-activites@fasoim.test",
            password=self.mot_de_passe,
            first_name="Formateur",
            last_name="Principal",
        )
        self.formateur_2 = Acteur.objects.create_user(
            username="formateur-activites-2",
            email="formateur-activites-2@fasoim.test",
            password=self.mot_de_passe,
            first_name="Formateur",
            last_name="Secondaire",
        )

        self.session = SessionImmersion.objects.create(
            nom="Session activités 2026",
            annee=2026,
            numero_promotion=3,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=date(2026, 8, 1),
            date_fin=date(2026, 8, 31),
            statut=SessionImmersion.Statut.EN_PREPARATION,
        )
        self.parametres = ParametreSession.objects.create(
            session=self.session,
            activites_active=activites_active,
            evaluation_active=evaluation_active,
            visite_medicale_active=visite_medicale_active,
            taux_presence_minimum_attestation=Decimal("80.00"),
        )

        self.region = RegionImmersion.objects.create(
            code="REG-ACT",
            nom="Région activités",
        )
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="CTR-ACT-001",
            nom="Centre activités principal",
            province="Kadiogo",
            ville="Ouagadougou",
            genre=CentreImmersion.Genre.MIXTE,
            publics_acceptes=[],
            niveaux_acceptes=[],
        )
        self.centre_2 = CentreImmersion.objects.create(
            region=self.region,
            code="CTR-ACT-002",
            nom="Centre activités secondaire",
            province="Kadiogo",
            ville="Ouagadougou",
            genre=CentreImmersion.Genre.MIXTE,
            publics_acceptes=[],
            niveaux_acceptes=[],
        )

        self.section = Section.objects.create(
            session=self.session,
            centre=self.centre,
            nom="Section A",
            code="SEC-ACT-A",
            capacite_max=100,
        )
        self.groupe = Groupe.objects.create(
            section=self.section,
            nom="Groupe A1",
            code="GRP-ACT-A1",
            capacite_max=50,
        )
        self.groupe_2 = Groupe.objects.create(
            section=self.section,
            nom="Groupe A2",
            code="GRP-ACT-A2",
            capacite_max=50,
        )

        self.affectation_1 = self.creer_affectation(
            1,
            groupe=self.groupe,
        )
        self.affectation_2 = self.creer_affectation(2)

    def creer_affectation(
        self,
        numero,
        *,
        centre=None,
        groupe=None,
    ):
        centre = centre or self.centre
        immerge = Immerge.objects.create(
            session=self.session,
            type_immerge=Immerge.TypeImmerge.SELECTIONNE,
            origine_id=40_000 + numero,
            code_fasoim=f"IP2026SEL03{numero:05d}",
            statut=Immerge.Statut.AFFECTE_CENTRE,
        )
        affectation_regionale = AffectationRegionale.objects.create(
            immerge=immerge,
            session=self.session,
            region=self.region,
            statut=AffectationRegionale.Statut.ACTIVE,
            affecte_par=self.acteur,
        )
        affectation = AffectationCentre.objects.create(
            immerge=immerge,
            session=self.session,
            affectation_regionale=affectation_regionale,
            centre=centre,
            statut=AffectationCentre.Statut.ACTIVE,
            affecte_par=self.acteur,
        )
        if groupe is not None:
            AffectationGroupe.objects.create(
                affectation_centre=affectation,
                groupe=groupe,
                statut=AffectationGroupe.Statut.ACTIVE,
                affecte_par=self.acteur,
            )
        return affectation

    def affecter_au_groupe(self, affectation, groupe=None):
        return AffectationGroupe.objects.create(
            affectation_centre=affectation,
            groupe=groupe or self.groupe,
            statut=AffectationGroupe.Statut.ACTIVE,
            affecte_par=self.acteur,
        )

    def creer_module(
        self,
        *,
        code="CIV-001",
        titre="Civisme et citoyenneté",
        categorie=ModuleActivite.Categorie.CIVISME,
        duree_prevue=90,
        ordre=1,
        statut=ModuleActivite.Statut.ACTIF,
    ):
        return ModuleActivite.objects.create(
            code=code,
            titre=titre,
            description="Module de test.",
            categorie=categorie,
            duree_prevue=duree_prevue,
            ordre=ordre,
            statut=statut,
        )

    def creer_seance(
        self,
        *,
        module=None,
        centre=None,
        section=None,
        groupe=None,
        formateur=None,
        date_seance=date(2026, 8, 10),
        heure_debut=time(8, 0),
        heure_fin=time(10, 0),
        statut=Seance.Statut.PLANIFIEE,
        titre="Séance de test",
        type_seance=Seance.TypeSeance.ACTIVITE,
    ):
        return Seance.objects.create(
            module_activite=(module or self.creer_module()) if type_seance == Seance.TypeSeance.ACTIVITE else None,
            type_seance=type_seance,
            session=self.session,
            centre=centre or self.centre,
            section=section,
            groupe=groupe,
            formateur=formateur,
            titre=titre,
            date_seance=date_seance,
            heure_debut=heure_debut,
            heure_fin=heure_fin,
            lieu="Salle polyvalente",
            statut=statut,
            observations="",
        )

    def creer_evaluation(
        self,
        *,
        seance=None,
        titre="Évaluation de civisme",
        bareme=Decimal("20.00"),
        coefficient=Decimal("1.00"),
        statut=Evaluation.Statut.BROUILLON,
        date_evaluation=None,
    ):
        seance = seance or self.creer_seance(type_seance=Seance.TypeSeance.EVALUATION)
        if seance.type_seance != Seance.TypeSeance.EVALUATION:
            seance.type_seance = Seance.TypeSeance.EVALUATION
            seance.module_activite = None
            seance.save(update_fields=["type_seance", "module_activite", "updated_at"])
        date_evaluation = date_evaluation or timezone.make_aware(
            datetime.combine(seance.date_seance, seance.heure_debut)
        )
        return Evaluation.objects.create(
            session=self.session,
            centre=self.centre,
            seance=seance,
            titre=titre,
            type_evaluation=Evaluation.TypeEvaluation.TEST,
            bareme=bareme,
            coefficient=coefficient,
            date_evaluation=date_evaluation,
            statut=statut,
            created_by=self.acteur,
        )

    @staticmethod
    def decision_autorisee(module="ACTIVITES"):
        return {
            "affectation_centre_id": 1,
            "module": module,
            "etat": "VISITE_NON_REQUISE",
            "resultat": None,
            "autorise": True,
            "dispense": False,
            "necessite_adaptation": False,
            "consignes": [],
        }

    @staticmethod
    def decision_dispense(module="ACTIVITES"):
        return {
            "affectation_centre_id": 1,
            "module": module,
            "etat": "AUTORISE_AVEC_CONSIGNES",
            "resultat": "APTE_SOUS_RESERVE",
            "autorise": False,
            "dispense": True,
            "necessite_adaptation": False,
            "consignes": [],
        }


class ModelesActivitesTests(ActivitesFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()

    def test_module_activite_est_independant_des_sessions(self):
        self.assertFalse(hasattr(ModuleActivite, "session"))
        module = self.creer_module()
        self.assertIsNone(
            getattr(module, "session_id", None)
        )

    def test_code_module_est_normalise_en_majuscules(self):
        module = self.creer_module(code=" civ-abc ")
        self.assertEqual(module.code, "CIV-ABC")

    def test_duree_prevue_doit_etre_positive(self):
        with self.assertRaises(ValidationError):
            self.creer_module(duree_prevue=0)

    def test_doublon_code_module_actif_est_refuse(self):
        self.creer_module()
        with self.assertRaises(
            (ValidationError, IntegrityError)
        ):
            self.creer_module(
                titre="Autre titre",
            )

    def test_suppression_logique_permet_reutiliser_code(self):
        module = self.creer_module()
        ancien_code = module.code

        module.supprimer_logiquement()
        nouveau = self.creer_module(
            code=ancien_code,
            titre="Nouveau module",
        )

        self.assertIsNotNone(module.deleted_at)
        self.assertEqual(nouveau.code, ancien_code)

    def test_seance_reprend_titre_module_par_defaut(self):
        module = self.creer_module()
        seance = self.creer_seance(module=module, titre="")

        self.assertEqual(seance.titre, module.titre)

    def test_seance_groupe_ne_duplique_pas_section(self):
        seance = self.creer_seance(groupe=self.groupe)

        self.assertEqual(seance.niveau_cible, "GROUPE")
        self.assertIsNone(seance.section_id)
        self.assertEqual(seance.groupe_id, self.groupe.id)

    def test_seance_section_est_identifiee(self):
        seance = self.creer_seance(section=self.section)
        self.assertEqual(seance.niveau_cible, "SECTION")

    def test_seance_centre_est_identifiee(self):
        seance = self.creer_seance()
        self.assertEqual(seance.niveau_cible, "CENTRE")

    def test_heure_fin_doit_suivre_heure_debut(self):
        with self.assertRaises(ValidationError):
            self.creer_seance(
                heure_debut=time(10, 0),
                heure_fin=time(9, 0),
            )

    def test_module_inactif_ne_peut_pas_etre_planifie(self):
        module = self.creer_module(
            statut=ModuleActivite.Statut.INACTIF
        )
        with self.assertRaises(ValidationError):
            self.creer_seance(module=module)

    def test_groupe_d_un_autre_centre_est_refuse(self):
        section = Section.objects.create(
            session=self.session,
            centre=self.centre_2,
            nom="Section secondaire",
            code="SEC-ACT-B",
            capacite_max=50,
        )
        groupe = Groupe.objects.create(
            section=section,
            nom="Groupe secondaire",
            code="GRP-ACT-B1",
            capacite_max=50,
        )

        with self.assertRaises(ValidationError):
            self.creer_seance(
                centre=self.centre,
                groupe=groupe,
            )

    def test_presence_unique_par_seance_et_affectation(self):
        seance = self.creer_seance()
        Presence.objects.create(
            seance=seance,
            affectation_centre=self.affectation_1,
            statut_presence=Presence.StatutPresence.PRESENT,
            saisie_par=self.acteur,
        )

        with self.assertRaises(
            (ValidationError, IntegrityError)
        ):
            Presence.objects.create(
                seance=seance,
                affectation_centre=self.affectation_1,
                statut_presence=Presence.StatutPresence.ABSENT,
                saisie_par=self.acteur,
            )

    def test_presence_refuse_affectation_autre_centre(self):
        autre = self.creer_affectation(
            3,
            centre=self.centre_2,
        )
        seance = self.creer_seance()

        with self.assertRaises(ValidationError):
            Presence.objects.create(
                seance=seance,
                affectation_centre=autre,
                statut_presence=Presence.StatutPresence.PRESENT,
                saisie_par=self.acteur,
            )

    def test_evaluation_refuse_coefficient_nul(self):
        with self.assertRaises(ValidationError):
            self.creer_evaluation(
                coefficient=Decimal("0.00")
            )

    def test_evaluation_est_une_seance_sans_module(self):
        evaluation = self.creer_evaluation()
        self.assertEqual(evaluation.seance.type_seance, Seance.TypeSeance.EVALUATION)
        self.assertIsNone(evaluation.module_activite)

    def test_note_ne_depasse_pas_bareme(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )

        with self.assertRaises(ValidationError):
            Note.objects.create(
                evaluation=evaluation,
                affectation_centre=self.affectation_1,
                valeur=Decimal("21.00"),
                statut_note=Note.StatutNote.NOTEE,
                saisie_par=self.acteur,
            )

    def test_absence_ne_contient_pas_de_valeur(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )

        with self.assertRaises(ValidationError):
            Note.objects.create(
                evaluation=evaluation,
                affectation_centre=self.affectation_1,
                valeur=Decimal("0.00"),
                statut_note=Note.StatutNote.ABSENT,
                saisie_par=self.acteur,
            )

    def test_suppression_logique_note_conserve_historique(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )
        note = Note.objects.create(
            evaluation=evaluation,
            affectation_centre=self.affectation_1,
            valeur=Decimal("15.00"),
            statut_note=Note.StatutNote.NOTEE,
            saisie_par=self.acteur,
        )

        note.supprimer_logiquement()

        self.assertIsNotNone(note.deleted_at)
        self.assertEqual(
            note.statut_note,
            Note.StatutNote.ANNULEE,
        )


class RepositoriesActivitesTests(
    ActivitesFixtureMixin,
    TestCase,
):
    def setUp(self):
        self.creer_socle()

    def test_filtre_modules_par_categorie(self):
        civisme = self.creer_module()
        self.creer_module(
            code="SPT-001",
            titre="Sport collectif",
            categorie=ModuleActivite.Categorie.SPORT,
        )

        ids = list(
            ModuleActiviteRepository.filtrer(
                categorie=ModuleActivite.Categorie.CIVISME
            ).values_list("id", flat=True)
        )

        self.assertEqual(ids, [civisme.id])

    def test_filtre_seances_par_session_et_centre(self):
        seance = self.creer_seance()

        ids = list(
            SeanceRepository.filtrer(
                session_id=self.session.id,
                centre_id=self.centre.id,
            ).values_list("id", flat=True)
        )

        self.assertEqual(ids, [seance.id])

    def test_detecte_chevauchement_formateur(self):
        self.creer_seance(formateur=self.formateur)

        conflit = SeanceRepository.chevauchement_formateur(
            formateur_id=self.formateur.id,
            date_seance=date(2026, 8, 10),
            heure_debut=time(9, 0),
            heure_fin=time(11, 0),
        )

        self.assertIsNotNone(conflit)

    def test_section_entre_en_conflit_avec_son_groupe(self):
        self.creer_seance(groupe=self.groupe)

        conflit = SeanceRepository.chevauchement_cible(
            session_id=self.session.id,
            centre_id=self.centre.id,
            date_seance=date(2026, 8, 10),
            heure_debut=time(9, 0),
            heure_fin=time(11, 0),
            section_id=self.section.id,
        )

        self.assertIsNotNone(conflit)

    def test_groupes_distincts_peuvent_partager_horaire(self):
        self.creer_seance(groupe=self.groupe)

        conflit = SeanceRepository.chevauchement_cible(
            session_id=self.session.id,
            centre_id=self.centre.id,
            date_seance=date(2026, 8, 10),
            heure_debut=time(9, 0),
            heure_fin=time(11, 0),
            groupe_id=self.groupe_2.id,
            groupe_section_id=self.section.id,
        )

        self.assertIsNone(conflit)

    def test_candidats_groupe_sont_limites_aux_affectes(self):
        ids = list(
            CandidatActiviteRepository.pour_seance(
                self.creer_seance(groupe=self.groupe)
            ).values_list("id", flat=True)
        )

        self.assertEqual(ids, [self.affectation_1.id])

    def test_candidats_centre_incluent_tous_les_affectes(self):
        ids = set(
            CandidatActiviteRepository.pour_seance(
                self.creer_seance()
            ).values_list("id", flat=True)
        )

        self.assertEqual(
            ids,
            {self.affectation_1.id, self.affectation_2.id},
        )

    def test_statistiques_presences_regroupent_statuts(self):
        seance = self.creer_seance()
        Presence.objects.create(
            seance=seance,
            affectation_centre=self.affectation_1,
            statut_presence=Presence.StatutPresence.PRESENT,
            saisie_par=self.acteur,
        )
        Presence.objects.create(
            seance=seance,
            affectation_centre=self.affectation_2,
            statut_presence=Presence.StatutPresence.ABSENT,
            saisie_par=self.acteur,
        )

        statistiques = {
            ligne["statut_presence"]: ligne["total"]
            for ligne in PresenceRepository.statistiques_seance(
                seance.id
            )
        }

        self.assertEqual(statistiques["PRESENT"], 1)
        self.assertEqual(statistiques["ABSENT"], 1)

    def test_statistiques_notes_regroupent_statuts(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )
        Note.objects.create(
            evaluation=evaluation,
            affectation_centre=self.affectation_1,
            valeur=Decimal("12.00"),
            statut_note=Note.StatutNote.NOTEE,
            saisie_par=self.acteur,
        )
        Note.objects.create(
            evaluation=evaluation,
            affectation_centre=self.affectation_2,
            valeur=None,
            statut_note=Note.StatutNote.ABSENT,
            saisie_par=self.acteur,
        )

        statistiques = {
            ligne["statut_note"]: ligne["total"]
            for ligne in NoteRepository.statistiques_evaluation(
                evaluation.id
            )
        }

        self.assertEqual(statistiques["NOTEE"], 1)
        self.assertEqual(statistiques["ABSENT"], 1)


class ServicesActivitesTests(
    ActivitesFixtureMixin,
    TestCase,
):
    def setUp(self):
        self.creer_socle()

    def test_service_cree_activite_globale(self):
        module = ActiviteService.creer_activite(
            acteur=self.acteur,
            titre="Orientation professionnelle",
            categorie=ModuleActivite.Categorie.ORIENTATION,
            duree_prevue=60,
        )

        self.assertTrue(module.code.startswith("ACT-ORI-"))
        self.assertFalse(hasattr(module, "session_id"))

    def test_service_refuse_doublon_activite(self):
        self.creer_module()

        with self.assertRaises(ValidationActiviteErreur):
            ActiviteService.creer_activite(
                acteur=self.acteur,
                titre="Civisme et citoyenneté",
                categorie=ModuleActivite.Categorie.CIVISME,
            )

    def test_planification_seance_centre(self):
        module = self.creer_module()

        seance = SeanceService.planifier_seance(
            acteur=self.acteur,
            module_activite_id=module.id,
            session_id=self.session.id,
            centre_id=self.centre.id,
            date_seance=date(2026, 8, 12),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            lieu="Salle A",
        )

        self.assertEqual(seance.niveau_cible, "CENTRE")
        self.assertEqual(seance.statut, Seance.Statut.PLANIFIEE)

    def test_planification_refuse_module_activites_desactive(self):
        self.parametres.activites_active = False
        self.parametres.save(
            update_fields=["activites_active", "updated_at"]
        )
        module = self.creer_module()

        with self.assertRaises(ValidationActiviteErreur):
            SeanceService.planifier_seance(
                acteur=self.acteur,
                module_activite_id=module.id,
                session_id=self.session.id,
                centre_id=self.centre.id,
                date_seance=date(2026, 8, 12),
                heure_debut=time(8, 0),
                heure_fin=time(10, 0),
                lieu="Salle A",
            )

    def test_planification_refuse_chevauchement_formateur(self):
        module = self.creer_module()
        self.creer_seance(
            module=module,
            formateur=self.formateur,
        )

        with self.assertRaises(ValidationActiviteErreur):
            SeanceService.planifier_seance(
                acteur=self.acteur,
                module_activite_id=module.id,
                session_id=self.session.id,
                centre_id=self.centre.id,
                groupe_id=self.groupe_2.id,
                formateur_id=self.formateur.id,
                date_seance=date(2026, 8, 10),
                heure_debut=time(9, 0),
                heure_fin=time(11, 0),
                lieu="Salle B",
            )

    def test_planification_refuse_chevauchement_groupe(self):
        module = self.creer_module()
        self.creer_seance(
            module=module,
            groupe=self.groupe,
        )

        with self.assertRaises(ValidationActiviteErreur):
            SeanceService.planifier_seance(
                acteur=self.acteur,
                module_activite_id=module.id,
                session_id=self.session.id,
                centre_id=self.centre.id,
                groupe_id=self.groupe.id,
                date_seance=date(2026, 8, 10),
                heure_debut=time(9, 0),
                heure_fin=time(11, 0),
                lieu="Salle B",
            )

    def test_report_cree_nouvelle_seance(self):
        ancienne = self.creer_seance()

        resultat = SeanceService.reporter_seance(
            ancienne.id,
            acteur=self.acteur,
            nouvelle_date=date(2026, 8, 15),
        )

        ancienne.refresh_from_db()
        self.assertEqual(
            ancienne.statut,
            Seance.Statut.REPORTEE,
        )
        self.assertEqual(
            resultat["nouvelle_seance"].date_seance,
            date(2026, 8, 15),
        )

    def test_affecter_formateur_a_seance(self):
        seance = self.creer_seance()

        seance = SeanceService.affecter_formateur(
            seance.id,
            acteur=self.acteur,
            formateur_id=self.formateur.id,
        )

        self.assertEqual(seance.formateur_id, self.formateur.id)

    def test_ouvrir_et_preparer_feuille_complete(self):
        seance = self.creer_seance()

        resultat = PresenceService.preparer_feuille_complete(
            seance_id=seance.id,
            acteur=self.acteur,
        )

        seance.refresh_from_db()
        self.assertEqual(
            seance.statut_feuille_presence,
            Seance.StatutFeuillePresence.OUVERTE,
        )
        self.assertEqual(resultat.crees, 2)
        self.assertEqual(
            Presence.objects.filter(seance=seance).count(),
            2,
        )

    def test_preparation_feuille_est_idempotente(self):
        seance = self.creer_seance()

        premiere = PresenceService.preparer_feuille_complete(
            seance_id=seance.id,
            acteur=self.acteur,
        )
        seconde = PresenceService.preparer_feuille_complete(
            seance_id=seance.id,
            acteur=self.acteur,
        )

        self.assertEqual(premiere.crees, 2)
        self.assertEqual(seconde.crees, 0)

    def test_retard_exige_heure_arrivee(self):
        seance = self.creer_seance(groupe=self.groupe)
        PresenceService.ouvrir_feuille_presence(
            seance.id,
            acteur=self.acteur,
        )

        with self.assertRaises(ValidationActiviteErreur):
            PresenceService.saisir_presence(
                seance_id=seance.id,
                affectation_centre_id=self.affectation_1.id,
                statut_presence=Presence.StatutPresence.RETARD,
                acteur=self.acteur,
            )

    @patch(
        "activites.service."
        "ImpactMedicalService.decision_pour_module"
    )
    def test_dispense_medicale_devient_presence_dispensee(
        self,
        decision,
    ):
        decision.side_effect = [
            self.decision_dispense("ACTIVITES"),
            self.decision_dispense("PRESENCES"),
        ]
        seance = self.creer_seance(groupe=self.groupe)
        PresenceService.ouvrir_feuille_presence(
            seance.id,
            acteur=self.acteur,
        )

        presence = PresenceService.saisir_presence(
            seance_id=seance.id,
            affectation_centre_id=self.affectation_1.id,
            statut_presence=Presence.StatutPresence.PRESENT,
            acteur=self.acteur,
        )

        self.assertEqual(
            presence.statut_presence,
            Presence.StatutPresence.DISPENSE,
        )

    def test_validation_feuille_refuse_presence_manquante(self):
        seance = self.creer_seance()
        PresenceService.ouvrir_feuille_presence(
            seance.id,
            acteur=self.acteur,
        )

        with self.assertRaises(ValidationActiviteErreur):
            PresenceService.valider_feuille_presence(
                seance.id,
                acteur=self.acteur,
            )

    def test_validation_puis_cloture_feuille(self):
        seance = self.creer_seance()
        PresenceService.preparer_feuille_complete(
            seance_id=seance.id,
            acteur=self.acteur,
        )

        PresenceService.valider_feuille_presence(
            seance.id,
            acteur=self.acteur,
        )
        seance = PresenceService.cloturer_feuille_presence(
            seance.id,
            acteur=self.acteur,
        )

        self.assertEqual(
            seance.statut_feuille_presence,
            Seance.StatutFeuillePresence.CLOTUREE,
        )

    def test_calcul_taux_presence_ignore_dispenses(self):
        seance_1 = self.creer_seance(
            groupe=self.groupe,
            date_seance=date(2026, 8, 10),
        )
        seance_2 = self.creer_seance(
            module=self.creer_module(
                code="CIV-002",
                titre="Civisme avancé",
            ),
            groupe=self.groupe,
            date_seance=date(2026, 8, 11),
        )

        for seance, statut in (
            (seance_1, Presence.StatutPresence.PRESENT),
            (seance_2, Presence.StatutPresence.DISPENSE),
        ):
            PresenceService.ouvrir_feuille_presence(
                seance.id,
                acteur=self.acteur,
            )
            PresenceService.saisir_presence(
                seance_id=seance.id,
                affectation_centre_id=self.affectation_1.id,
                statut_presence=statut,
                acteur=self.acteur,
            )
            PresenceService.valider_feuille_presence(
                seance.id,
                acteur=self.acteur,
            )
            PresenceService.cloturer_feuille_presence(
                seance.id,
                acteur=self.acteur,
            )

        resultat = PresenceService.calculer_taux_presence(
            affectation_centre_id=self.affectation_1.id,
            session_id=self.session.id,
            acteur=self.acteur,
        )

        self.assertEqual(
            resultat["taux_presence"],
            Decimal("100.00"),
        )
        self.assertEqual(resultat["dispenses"], 1)

    def test_creation_evaluation_commence_en_brouillon(self):
        seance = self.creer_seance(
            type_seance=Seance.TypeSeance.EVALUATION
        )
        evaluation = EvaluationService.creer_evaluation(
            acteur=self.acteur,
            session_id=self.session.id,
            centre_id=self.centre.id,
            titre="Test final",
            type_evaluation=Evaluation.TypeEvaluation.FINALE,
            bareme=Decimal("20.00"),
            coefficient=Decimal("2.00"),
            seance_id=seance.id,
            date_evaluation=timezone.make_aware(
                datetime(2026, 8, 20, 9, 0)
            ),
        )

        self.assertEqual(
            evaluation.statut,
            Evaluation.Statut.BROUILLON,
        )

    def test_creation_evaluation_refuse_module_desactive(self):
        self.parametres.evaluation_active = False
        self.parametres.save(
            update_fields=["evaluation_active", "updated_at"]
        )

        with self.assertRaises(ValidationActiviteErreur):
            EvaluationService.creer_evaluation(
                acteur=self.acteur,
                session_id=self.session.id,
                centre_id=self.centre.id,
                titre="Test",
                type_evaluation=Evaluation.TypeEvaluation.TEST,
                bareme=Decimal("20.00"),
                coefficient=Decimal("1.00"),
                date_evaluation=timezone.make_aware(
                    datetime(2026, 8, 20, 9, 0)
                ),
            )

    def test_ouvrir_saisie_notes(self):
        evaluation = self.creer_evaluation()

        evaluation = EvaluationService.ouvrir_saisie_notes(
            evaluation.id,
            acteur=self.acteur,
        )

        self.assertEqual(
            evaluation.statut,
            Evaluation.Statut.OUVERTE,
        )

    def test_evaluation_ouverte_ne_se_modifie_plus(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )

        with self.assertRaises(ValidationActiviteErreur):
            EvaluationService.modifier_evaluation(
                evaluation.id,
                acteur=self.acteur,
                titre="Titre corrigé",
            )

    def test_saisir_note_individuelle(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )

        note = NoteService.saisir_note(
            evaluation_id=evaluation.id,
            affectation_centre_id=self.affectation_1.id,
            acteur=self.acteur,
            valeur=Decimal("16.00"),
            appreciation="Bon travail",
        )

        self.assertEqual(note.valeur, Decimal("16.00"))
        self.assertEqual(
            note.statut_note,
            Note.StatutNote.NOTEE,
        )

    def test_service_refuse_note_superieure_au_bareme(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )

        with self.assertRaises(ValidationActiviteErreur):
            NoteService.saisir_note(
                evaluation_id=evaluation.id,
                affectation_centre_id=self.affectation_1.id,
                acteur=self.acteur,
                valeur=Decimal("25.00"),
            )

    @patch(
        "activites.service."
        "ImpactMedicalService.decision_pour_module"
    )
    def test_dispense_medicale_devient_note_dispensee(
        self,
        decision,
    ):
        decision.return_value = self.decision_dispense(
            "EVALUATIONS"
        )
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )

        note = NoteService.saisir_note(
            evaluation_id=evaluation.id,
            affectation_centre_id=self.affectation_1.id,
            acteur=self.acteur,
            valeur=Decimal("18.00"),
        )

        self.assertIsNone(note.valeur)
        self.assertEqual(
            note.statut_note,
            Note.StatutNote.DISPENSE,
        )

    def test_validation_resultats_refuse_notes_manquantes(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )
        NoteService.saisir_note(
            evaluation_id=evaluation.id,
            affectation_centre_id=self.affectation_1.id,
            acteur=self.acteur,
            valeur=Decimal("15.00"),
        )

        with self.assertRaises(ValidationActiviteErreur):
            EvaluationService.valider_resultats(
                evaluation.id,
                acteur=self.acteur,
            )

    def test_validation_resultats_cloture_evaluation_complete(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )
        NoteService.saisir_note(
            evaluation_id=evaluation.id,
            affectation_centre_id=self.affectation_1.id,
            acteur=self.acteur,
            valeur=Decimal("15.00"),
        )
        NoteService.saisir_note(
            evaluation_id=evaluation.id,
            affectation_centre_id=self.affectation_2.id,
            acteur=self.acteur,
            statut_note=Note.StatutNote.ABSENT,
        )

        evaluation = EvaluationService.valider_resultats(
            evaluation.id,
            acteur=self.acteur,
        )

        self.assertEqual(
            evaluation.statut,
            Evaluation.Statut.CLOTUREE,
        )

    def test_calcul_moyenne_ponderee_sur_vingt(self):
        seance = self.creer_seance()
        evaluation_1 = self.creer_evaluation(
            seance=seance,
            titre="Évaluation 1",
            coefficient=Decimal("1.00"),
            statut=Evaluation.Statut.CLOTUREE,
        )
        evaluation_2 = self.creer_evaluation(
            seance=self.creer_seance(type_seance=Seance.TypeSeance.EVALUATION, date_seance=date(2026, 8, 12), heure_debut=time(11, 0), heure_fin=time(12, 0), titre="Évaluation 2"),
            titre="Évaluation 2",
            coefficient=Decimal("2.00"),
            statut=Evaluation.Statut.CLOTUREE,
            date_evaluation=timezone.make_aware(
                datetime(2026, 8, 12, 11, 0)
            ),
        )
        Note.objects.create(
            evaluation=evaluation_1,
            affectation_centre=self.affectation_1,
            valeur=Decimal("10.00"),
            statut_note=Note.StatutNote.NOTEE,
            saisie_par=self.acteur,
        )
        Note.objects.create(
            evaluation=evaluation_2,
            affectation_centre=self.affectation_1,
            valeur=Decimal("20.00"),
            statut_note=Note.StatutNote.NOTEE,
            saisie_par=self.acteur,
        )

        resultat = NoteService.calculer_moyenne(
            affectation_centre_id=self.affectation_1.id,
            session_id=self.session.id,
            acteur=self.acteur,
        )

        self.assertEqual(
            resultat["moyenne_sur_20"],
            Decimal("16.67"),
        )


class SerializersActivitesTests(SimpleTestCase):
    def test_seance_refuse_horaire_inverse(self):
        serializer = SeanceCreateSerializer(
            data={
                "module_activite_id": 1,
                "session_id": 1,
                "centre_id": 1,
                "date_seance": "2026-08-10",
                "heure_debut": "10:00:00",
                "heure_fin": "09:00:00",
                "lieu": "Salle A",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("heure_fin", serializer.errors)

    def test_retard_exige_heure_arrivee(self):
        serializer = PresenceCreateSerializer(
            data={
                "seance_id": 1,
                "affectation_centre_id": 2,
                "statut_presence": "RETARD",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("heure_arrivee", serializer.errors)

    def test_notee_exige_valeur(self):
        serializer = NoteCreateSerializer(
            data={
                "evaluation_id": 1,
                "affectation_centre_id": 2,
                "statut_note": "NOTEE",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("valeur", serializer.errors)

    def test_absence_force_valeur_nulle(self):
        serializer = NoteCreateSerializer(
            data={
                "evaluation_id": 1,
                "affectation_centre_id": 2,
                "statut_note": "ABSENT",
                "valeur": "10.00",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIsNone(serializer.validated_data["valeur"])

    def test_filtre_seance_exige_perimetre(self):
        serializer = FiltreSeanceSerializer(data={})
        self.assertFalse(serializer.is_valid())

    def test_saisie_masse_refuse_affectation_dupliquee(self):
        serializer = SaisiePresencesMasseSerializer(
            data={
                "seance_id": 1,
                "lignes": [
                    {
                        "affectation_centre_id": 2,
                        "statut_presence": "PRESENT",
                    },
                    {
                        "affectation_centre_id": 2,
                        "statut_presence": "ABSENT",
                    },
                ],
            }
        )

        self.assertFalse(serializer.is_valid())

    def test_evaluation_api_impose_brouillon(self):
        serializer = EvaluationCreateSerializer(
            data={
                "session_id": 1,
                "centre_id": 1,
                "seance_id": 1,
                "titre": "Test",
                "type_evaluation": "TEST",
                "bareme": "20.00",
                "coefficient": "1.00",
                "date_evaluation": "2026-08-10T10:00:00Z",
                "statut": "CLOTUREE",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["statut"],
            Evaluation.Statut.BROUILLON,
        )

    def test_ligne_note_masse_valide_absence(self):
        serializer = LigneNoteMasseSerializer(
            data={
                "affectation_centre_id": 1,
                "statut_note": "ABSENT",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)


@override_settings(CACHES=CACHE_TEST)
class TachesActivitesTests(
    ActivitesFixtureMixin,
    TestCase,
):
    def setUp(self):
        cache.clear()
        self.creer_socle()

    def test_progression_est_stockee_dans_cache(self):
        ProgressionActivitesService.definir(
            "task-act",
            operation="test",
            statut=ProgressionActivitesService.EN_COURS,
            progression=40,
            total=10,
            traites=4,
        )

        progression = ProgressionActivitesService.lire(
            "task-act"
        )

        self.assertEqual(progression["progression"], 40)
        self.assertEqual(progression["traites"], 4)

    def test_verrou_refuse_operation_concurrente(self):
        with ProgressionActivitesService.verrou(
            "preparation",
            cible="seance:1",
        ) as premier:
            with ProgressionActivitesService.verrou(
                "preparation",
                cible="seance:1",
            ) as second:
                self.assertTrue(premier)
                self.assertFalse(second)

    def test_tache_prepare_feuille_complete(self):
        seance = self.creer_seance()

        resultat_celery = (
            ouvrir_et_preparer_feuille_presence_task.apply(
                kwargs={
                    "seance_id": seance.id,
                    "acteur_id": self.acteur.id,
                }
            )
        )
        resultat = resultat_celery.get(propagate=True)

        self.assertTrue(resultat["ok"])
        self.assertEqual(resultat["crees"], 2)

    def test_tache_saisie_presences_masse(self):
        seance = self.creer_seance()
        PresenceService.preparer_feuille_complete(
            seance_id=seance.id,
            acteur=self.acteur,
        )

        resultat_celery = saisir_presences_masse_task.apply(
            kwargs={
                "seance_id": seance.id,
                "acteur_id": self.acteur.id,
                "lignes": [
                    {
                        "affectation_centre_id": (
                            self.affectation_1.id
                        ),
                        "statut_presence": "PRESENT",
                    },
                    {
                        "affectation_centre_id": (
                            self.affectation_2.id
                        ),
                        "statut_presence": "ABSENT",
                    },
                ],
            }
        )
        resultat = resultat_celery.get(propagate=True)

        self.assertTrue(resultat["ok"])
        self.assertEqual(resultat["mis_a_jour"], 2)

    def test_tache_saisie_notes_masse(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )

        resultat_celery = saisir_notes_masse_task.apply(
            kwargs={
                "evaluation_id": evaluation.id,
                "acteur_id": self.acteur.id,
                "lignes": [
                    {
                        "affectation_centre_id": (
                            self.affectation_1.id
                        ),
                        "statut_note": "NOTEE",
                        "valeur": "14.00",
                    },
                    {
                        "affectation_centre_id": (
                            self.affectation_2.id
                        ),
                        "statut_note": "ABSENT",
                    },
                ],
            }
        )
        resultat = resultat_celery.get(propagate=True)

        self.assertTrue(resultat["ok"])
        self.assertEqual(resultat["crees"], 2)

    def test_tache_validation_resultats_cloture(self):
        evaluation = self.creer_evaluation(
            statut=Evaluation.Statut.OUVERTE
        )
        NoteService.saisir_note(
            evaluation_id=evaluation.id,
            affectation_centre_id=self.affectation_1.id,
            acteur=self.acteur,
            valeur=Decimal("12.00"),
        )
        NoteService.saisir_note(
            evaluation_id=evaluation.id,
            affectation_centre_id=self.affectation_2.id,
            acteur=self.acteur,
            statut_note=Note.StatutNote.ABSENT,
        )

        resultat_celery = valider_resultats_masse_task.apply(
            kwargs={
                "evaluation_ids": [evaluation.id],
                "acteur_id": self.acteur.id,
            }
        )
        resultat = resultat_celery.get(propagate=True)

        evaluation.refresh_from_db()
        self.assertTrue(resultat["ok"])
        self.assertEqual(
            evaluation.statut,
            Evaluation.Statut.CLOTUREE,
        )


class PermissionsRoutesSeedActivitesTests(SimpleTestCase):
    def test_permissions_api_correspondent_actions(self):
        self.assertEqual(
            PermissionModuleActivite.action_permission_map[
                "create"
            ],
            "creer_activite",
        )
        self.assertEqual(
            PermissionSeance.action_permission_map["reporter"],
            "reporter_seance",
        )
        self.assertEqual(
            PermissionPresence.action_permission_map[
                "valider_feuille"
            ],
            "valider_presence",
        )
        self.assertEqual(
            PermissionEvaluation.action_permission_map[
                "valider_resultats"
            ],
            "valider_resultats",
        )
        self.assertEqual(
            PermissionNote.action_permission_map["moyenne"],
            "calculer_moyenne",
        )
        self.assertEqual(
            PermissionOperationActivite.action_permission_map[
                "retrieve"
            ],
            "consulter_progression_activites",
        )

    def test_routes_principales_sont_resolues(self):
        attentes = {
            "/api/activites/activites/": (
                "activites:activites-list"
            ),
            "/api/activites/seances/": (
                "activites:seances-list"
            ),
            "/api/activites/presences/": (
                "activites:presences-list"
            ),
            "/api/activites/evaluations/": (
                "activites:evaluations-list"
            ),
            "/api/activites/notes/": (
                "activites:notes-list"
            ),
            "/api/activites/operations/preparer-feuille/": (
                "activites:operations-activites-preparer-feuille"
            ),
        }

        for chemin, nom_vue in attentes.items():
            with self.subTest(chemin=chemin):
                self.assertEqual(
                    resolve(chemin).view_name,
                    nom_vue,
                )

    def test_reverse_route_seances(self):
        self.assertEqual(
            reverse("activites:seances-list"),
            "/api/activites/seances/",
        )

    def test_permissions_activites_sont_dans_seed(self):
        codes_seed = {
            definition.code
            for definition in PERMISSIONS_SYSTEME
            if definition.module == "activites"
        }
        codes_attendus = {
            "consulter_activites",
            "creer_activite",
            "modifier_activite",
            "desactiver_activite",
            "consulter_seances",
            "planifier_seance",
            "modifier_seance",
            "annuler_seance",
            "reporter_seance",
            "affecter_formateur_seance",
            "consulter_presences",
            "ouvrir_feuille_presence",
            "saisir_presence",
            "modifier_presence",
            "valider_presence",
            "cloturer_feuille_presence",
            "calculer_taux_presence",
            "consulter_evaluations",
            "creer_evaluation",
            "modifier_evaluation",
            "ouvrir_saisie_notes",
            "cloturer_evaluation",
            "annuler_evaluation",
            "consulter_resultats",
            "valider_resultats",
            "consulter_notes",
            "saisir_note",
            "modifier_note",
            "marquer_absence_note",
            "marquer_dispense_note",
            "annuler_note",
            "calculer_moyenne",
            "consulter_progression_activites",
        }

        self.assertEqual(codes_seed, codes_attendus)

    def test_catalogue_seed_ne_contient_pas_de_codes_dupliques(self):
        codes = [
            definition.code
            for definition in PERMISSIONS_SYSTEME
        ]
        self.assertEqual(len(codes), len(set(codes)))


class ApiActivitesTests(ActivitesFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.client = APIClient()
        self.client.force_authenticate(self.acteur)

    def test_creation_activite_par_api(self):
        reponse = self.client.post(
            "/api/activites/activites/",
            {
                "titre": "Sport API",
                "categorie": "SPORT",
                "duree_prevue": 60,
            },
            format="json",
        )

        self.assertEqual(reponse.status_code, 201)
        self.assertTrue(reponse.data["code"].startswith("ACT-SPO-"))

    def test_liste_seances_accepte_perimetre(self):
        self.creer_seance()

        reponse = self.client.get(
            "/api/activites/seances/",
            {"session_id": self.session.id},
        )

        self.assertEqual(reponse.status_code, 200)

    def test_ouverture_feuille_par_api(self):
        seance = self.creer_seance()

        reponse = self.client.post(
            "/api/activites/presences/ouvrir-feuille/",
            {"seance_id": seance.id},
            format="json",
        )

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(
            reponse.data["statut_feuille_presence"],
            "OUVERTE",
        )

    def test_creation_evaluation_par_api(self):
        seance = self.creer_seance(
            type_seance=Seance.TypeSeance.EVALUATION
        )
        reponse = self.client.post(
            "/api/activites/evaluations/",
            {
                "session_id": self.session.id,
                "centre_id": self.centre.id,
                "seance_id": seance.id,
                "titre": "Évaluation API",
                "type_evaluation": "TEST",
                "bareme": "20.00",
                "coefficient": "1.00",
                "date_evaluation": "2026-08-15T10:00:00Z",
            },
            format="json",
        )

        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(reponse.data["statut"], "BROUILLON")

    def test_programmation_evaluation_cree_seance_evaluation(self):
        reponse = self.client.post(
            "/api/activites/evaluations/programmer/",
            {
                "session_id": self.session.id,
                "centre_id": self.centre.id,
                "module_activite_id": self.module.id,
                "formateur_id": self.formateur.id,
                "titre": "Évaluation programmée",
                "date_seance": "2026-08-15",
                "heure_debut": "10:00:00",
                "heure_fin": "11:00:00",
                "lieu": "Salle 1",
                "type_evaluation": "TEST",
                "bareme": "20.00",
                "coefficient": "1.00",
                "observations": "",
            },
            format="json",
        )

        self.assertEqual(reponse.status_code, 201, reponse.data)
        evaluation = Evaluation.objects.get(id=reponse.data["id"])
        self.assertEqual(
            evaluation.seance.type_seance,
            Seance.TypeSeance.EVALUATION,
        )
        self.assertEqual(evaluation.seance.titre, "Évaluation programmée")
        self.assertEqual(evaluation.seance.module_activite_id, self.module.id)
        self.assertEqual(evaluation.seance.formateur_id, self.formateur.id)

    @patch(
        "activites.views."
        "ouvrir_et_preparer_feuille_presence_task.delay"
    )
    def test_api_lance_preparation_celery(self, delay):
        seance = self.creer_seance()
        delay.return_value = SimpleNamespace(
            id="task-activites-123"
        )

        reponse = self.client.post(
            "/api/activites/operations/preparer-feuille/",
            {"seance_id": seance.id},
            format="json",
        )

        self.assertEqual(reponse.status_code, 202)
        self.assertEqual(
            reponse.data["task_id"],
            "task-activites-123",
        )

    def test_api_refuse_utilisateur_non_authentifie(self):
        client = APIClient()

        reponse = client.get(
            "/api/activites/seances/",
            {"session_id": self.session.id},
        )

        self.assertIn(reponse.status_code, {401, 403})
