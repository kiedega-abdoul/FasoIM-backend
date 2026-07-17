from datetime import timedelta
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
from sante.models import VisiteMedicale
from sessions_app.models import ParametreSession, SessionImmersion

from .models import ArticleKit, RemiseKit
from .permissions import (
    PermissionArticleKit,
    PermissionOperationKits,
    PermissionRemiseKit,
)
from .repository import (
    ArticleKitRepository,
    CandidatRemiseKitRepository,
    RemiseKitRepository,
)
from .serializers import (
    ArticleKitCreateSerializer,
    ArticleKitSerializer,
    FiltreArticleKitSerializer,
    FiltreRemiseKitSerializer,
    OperationMasseKitsSerializer,
)
from .service import (
    ArticleKitService,
    EligibiliteRemiseKitService,
    RemiseKitService,
    ValidationKitErreur,
)
from .tasks import (
    ProgressionKitsService,
    preparer_remises_centre_task,
    valider_remises_immerges_task,
)


CACHE_TEST = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends.locmem.LocMemCache"
        ),
        "LOCATION": "tests-kits",
    }
}


class KitsFixtureMixin:
    mot_de_passe = "Test-Kits-2026!"

    def creer_socle(self, *, visite_medicale_active=False):
        self.agent = Acteur.objects.create_user(
            username="responsable-kits-tests",
            email="responsable-kits-tests@fasoim.test",
            password=self.mot_de_passe,
            first_name="Responsable",
            last_name="Kits",
        )
        self.agent.is_superuser = True
        self.agent.is_staff = True
        self.agent.save(
            update_fields=[
                "is_superuser",
                "is_staff",
            ]
        )

        self.session = SessionImmersion.objects.create(
            nom="Session kits 2026",
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
            code="REG-KITS",
            nom="Région kits",
        )
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="CTR-KITS-001",
            nom="Centre kits",
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
            origine_id=30_000 + numero,
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

    def creer_article(
        self,
        *,
        designation="Tenue officielle",
        type_kit=ArticleKit.TypeKit.A_REMETTRE,
        centre=None,
        quantite=1,
        obligatoire=True,
    ):
        return ArticleKit.objects.create(
            session=self.session,
            centre=centre,
            designation=designation,
            description="Article de test.",
            type_kit=type_kit,
            quantite=quantite,
            unite="unité",
            obligatoire=obligatoire,
            ordre=1,
        )

    def creer_visite_apte(self, affectation):
        visite = VisiteMedicale.objects.create(
            affectation_centre=affectation,
            resultat=VisiteMedicale.Resultat.APTE,
            agent_sante=self.agent,
        )
        visite.valider(agent_sante=self.agent)
        return visite


class ModelesKitsTests(KitsFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.affectation = self.creer_affectation(1)

    def test_article_a_remettre_peut_etre_global(self):
        article = self.creer_article()

        self.assertIsNone(article.centre_id)
        self.assertTrue(article.est_a_remettre)
        self.assertTrue(article.est_actif)

    def test_article_a_apporter_peut_etre_lie_au_centre(self):
        article = self.creer_article(
            designation="Chaussures de sport",
            type_kit=ArticleKit.TypeKit.A_APPORTER,
            centre=self.centre,
        )

        self.assertTrue(article.est_a_apporter)
        self.assertEqual(article.centre_id, self.centre.id)

    def test_quantite_article_doit_etre_positive(self):
        with self.assertRaises(ValidationError):
            self.creer_article(quantite=0)

    def test_article_actif_refuse_session_annulee(self):
        self.session.statut = SessionImmersion.Statut.ANNULEE
        self.session.save(update_fields=["statut", "updated_at"])

        with self.assertRaises(ValidationError):
            self.creer_article()

    def test_doublon_article_global_actif_est_refuse(self):
        self.creer_article()

        with self.assertRaises(
            (ValidationError, IntegrityError)
        ):
            self.creer_article()

    def test_meme_designation_avec_types_differents_est_autorisee(self):
        self.creer_article(
            designation="Tenue",
            type_kit=ArticleKit.TypeKit.A_REMETTRE,
        )
        article = self.creer_article(
            designation="Tenue",
            type_kit=ArticleKit.TypeKit.A_APPORTER,
            centre=self.centre,
        )

        self.assertEqual(article.type_kit, "A_APPORTER")

    def test_suppression_article_est_logique(self):
        article = self.creer_article()

        article.supprimer_logiquement()

        self.assertIsNotNone(article.deleted_at)
        self.assertEqual(
            article.statut,
            ArticleKit.Statut.INACTIF,
        )
        self.assertTrue(
            ArticleKit.objects.filter(id=article.id).exists()
        )

    def test_remise_copie_quantite_prevue_article(self):
        article = self.creer_article(quantite=3)

        remise = RemiseKit.objects.create(
            affectation_centre=self.affectation,
            article_kit=article,
            quantite_remise=0,
            statut_remise=RemiseKit.StatutRemise.NON_REMIS,
        )

        self.assertEqual(remise.quantite_prevue, 3)

    def test_remise_refuse_article_a_apporter(self):
        article = self.creer_article(
            designation="Serviette",
            type_kit=ArticleKit.TypeKit.A_APPORTER,
            centre=self.centre,
        )

        with self.assertRaises(ValidationError):
            RemiseKit.objects.create(
                affectation_centre=self.affectation,
                article_kit=article,
                quantite_remise=0,
                statut_remise=(
                    RemiseKit.StatutRemise.NON_REMIS
                ),
            )

    def test_quantite_remise_ne_depasse_pas_prevue(self):
        article = self.creer_article(quantite=2)

        with self.assertRaises(ValidationError):
            RemiseKit.objects.create(
                affectation_centre=self.affectation,
                article_kit=article,
                quantite_prevue=2,
                quantite_remise=3,
                statut_remise=RemiseKit.StatutRemise.REMIS,
            )

    def test_statut_remis_exige_quantite_complete(self):
        article = self.creer_article(quantite=2)

        with self.assertRaises(ValidationError):
            RemiseKit.objects.create(
                affectation_centre=self.affectation,
                article_kit=article,
                quantite_prevue=2,
                quantite_remise=1,
                statut_remise=RemiseKit.StatutRemise.REMIS,
            )

    def test_statut_partiel_exige_quantite_intermediaire(self):
        article = self.creer_article(quantite=3)
        remise = RemiseKit.objects.create(
            affectation_centre=self.affectation,
            article_kit=article,
            quantite_prevue=3,
            quantite_remise=1,
            statut_remise=RemiseKit.StatutRemise.PARTIEL,
        )

        self.assertEqual(
            remise.statut_remise,
            RemiseKit.StatutRemise.PARTIEL,
        )

    def test_enregistrer_quantite_calcule_statut(self):
        article = self.creer_article(quantite=2)
        remise = RemiseKit.objects.create(
            affectation_centre=self.affectation,
            article_kit=article,
            quantite_prevue=2,
            quantite_remise=0,
            statut_remise=RemiseKit.StatutRemise.NON_REMIS,
        )

        remise.enregistrer_quantite(1, acteur=self.agent)
        self.assertEqual(
            remise.statut_remise,
            RemiseKit.StatutRemise.PARTIEL,
        )

        remise.enregistrer_quantite(2, acteur=self.agent)
        self.assertEqual(
            remise.statut_remise,
            RemiseKit.StatutRemise.REMIS,
        )

    def test_marquer_dispense_ne_remet_aucune_quantite(self):
        article = self.creer_article(quantite=2)
        remise = RemiseKit.objects.create(
            affectation_centre=self.affectation,
            article_kit=article,
            quantite_prevue=2,
            quantite_remise=0,
            statut_remise=RemiseKit.StatutRemise.NON_REMIS,
        )

        remise.marquer_dispense(acteur=self.agent)

        self.assertEqual(remise.quantite_remise, 0)
        self.assertEqual(
            remise.statut_remise,
            RemiseKit.StatutRemise.DISPENSE,
        )
        self.assertTrue(remise.est_complete)

    def test_une_seule_remise_active_par_article_et_immerge(self):
        article = self.creer_article()
        RemiseKit.objects.create(
            affectation_centre=self.affectation,
            article_kit=article,
            quantite_prevue=1,
            quantite_remise=0,
            statut_remise=RemiseKit.StatutRemise.NON_REMIS,
        )

        with self.assertRaises(
            (ValidationError, IntegrityError)
        ):
            RemiseKit.objects.create(
                affectation_centre=self.affectation,
                article_kit=article,
                quantite_prevue=1,
                quantite_remise=0,
                statut_remise=(
                    RemiseKit.StatutRemise.NON_REMIS
                ),
            )


class RepositoriesKitsTests(KitsFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle()
        self.affectation_1 = self.creer_affectation(1)
        self.affectation_2 = self.creer_affectation(2)

    def test_articles_applicables_fusionnent_global_et_centre(self):
        global_article = self.creer_article(
            designation="Badge",
        )
        centre_article = self.creer_article(
            designation="Carnet local",
            centre=self.centre,
        )

        ids = set(
            ArticleKitRepository.a_remettre(
                session_id=self.session.id,
                centre_id=self.centre.id,
            ).values_list("id", flat=True)
        )

        self.assertEqual(
            ids,
            {global_article.id, centre_article.id},
        )

    def test_articles_a_apporter_sont_separes(self):
        apporter = self.creer_article(
            designation="Chaussures",
            type_kit=ArticleKit.TypeKit.A_APPORTER,
            centre=self.centre,
        )
        self.creer_article(
            designation="Badge",
            type_kit=ArticleKit.TypeKit.A_REMETTRE,
        )

        ids = list(
            ArticleKitRepository.a_apporter(
                session_id=self.session.id,
                centre_id=self.centre.id,
            ).values_list("id", flat=True)
        )

        self.assertEqual(ids, [apporter.id])

    def test_paires_existantes_evite_doubles_preparations(self):
        article = self.creer_article()
        remise = RemiseKit.objects.create(
            affectation_centre=self.affectation_1,
            article_kit=article,
            quantite_prevue=1,
            quantite_remise=0,
            statut_remise=RemiseKit.StatutRemise.NON_REMIS,
        )

        paires = RemiseKitRepository.paires_existantes(
            affectation_centre_ids=[self.affectation_1.id],
            article_kit_ids=[article.id],
        )

        self.assertEqual(
            paires,
            {(remise.affectation_centre_id, article.id)},
        )

    def test_candidats_sont_limites_au_centre(self):
        ids = list(
            CandidatRemiseKitRepository.filtrer(
                session_id=self.session.id,
                centre_id=self.centre.id,
            ).values_list("id", flat=True)
        )

        self.assertEqual(
            set(ids),
            {self.affectation_1.id, self.affectation_2.id},
        )

    def test_statistiques_regroupent_par_statut(self):
        article = self.creer_article()
        RemiseKit.objects.create(
            affectation_centre=self.affectation_1,
            article_kit=article,
            quantite_prevue=1,
            quantite_remise=1,
            statut_remise=RemiseKit.StatutRemise.REMIS,
            remis_par=self.agent,
        )
        RemiseKit.objects.create(
            affectation_centre=self.affectation_2,
            article_kit=article,
            quantite_prevue=1,
            quantite_remise=0,
            statut_remise=RemiseKit.StatutRemise.NON_REMIS,
        )

        statistiques = {
            ligne["statut_remise"]: ligne["total"]
            for ligne in RemiseKitRepository.statistiques(
                session_id=self.session.id,
                centre_id=self.centre.id,
            )
        }

        self.assertEqual(statistiques["REMIS"], 1)
        self.assertEqual(statistiques["NON_REMIS"], 1)


class SerializersKitsTests(SimpleTestCase):
    def test_article_a_apporter_exige_centre(self):
        serializer = ArticleKitCreateSerializer(
            data={
                "session_id": 1,
                "designation": "Chaussures",
                "type_kit": "A_APPORTER",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("centre_id", serializer.errors)

    def test_article_a_remettre_global_est_valide(self):
        serializer = ArticleKitCreateSerializer(
            data={
                "session_id": 1,
                "designation": "Badge",
                "type_kit": "A_REMETTRE",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_filtre_articles_exige_perimetre(self):
        serializer = FiltreArticleKitSerializer(data={})

        self.assertFalse(serializer.is_valid())

    def test_filtre_remises_exige_perimetre(self):
        serializer = FiltreRemiseKitSerializer(data={})

        self.assertFalse(serializer.is_valid())

    def test_operation_masse_dedoublonne_ids(self):
        serializer = OperationMasseKitsSerializer(
            data={
                "session_id": 1,
                "centre_id": 2,
                "affectation_centre_ids": [3, 3, 4],
                "article_kit_ids": [5, 5, 6],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data[
                "affectation_centre_ids"
            ],
            [3, 4],
        )
        self.assertEqual(
            serializer.validated_data["article_kit_ids"],
            [5, 6],
        )

    def test_serializer_article_n_expose_pas_deleted_at(self):
        self.assertNotIn(
            "deleted_at",
            ArticleKitSerializer.Meta.fields,
        )
        self.assertNotIn(
            "created_at",
            ArticleKitSerializer.Meta.fields,
        )
        self.assertNotIn(
            "updated_at",
            ArticleKitSerializer.Meta.fields,
        )


class ServicesKitsTests(KitsFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle(visite_medicale_active=False)
        self.affectation_1 = self.creer_affectation(1)
        self.affectation_2 = self.creer_affectation(2)

    def test_service_cree_article_a_remettre_global(self):
        article = ArticleKitService.creer(
            acteur=self.agent,
            session_id=self.session.id,
            designation="Badge",
            type_kit=ArticleKit.TypeKit.A_REMETTRE,
        )

        self.assertIsNone(article.centre_id)
        self.assertEqual(article.type_kit, "A_REMETTRE")

    def test_service_refuse_a_apporter_sans_centre(self):
        with self.assertRaises(ValidationKitErreur):
            ArticleKitService.creer(
                acteur=self.agent,
                session_id=self.session.id,
                designation="Chaussures",
                type_kit=ArticleKit.TypeKit.A_APPORTER,
            )

    @patch("kits.service.ControleAccesService.acteur_peut")
    def test_creation_a_remettre_utilise_permission_dgas(
        self,
        acteur_peut,
    ):
        self.agent.is_superuser = False
        self.agent.save(update_fields=["is_superuser"])
        acteur_peut.return_value = SimpleNamespace(
            autorise=True,
            affectation=None,
            motif="",
        )

        ArticleKitService.creer(
            acteur=self.agent,
            session_id=self.session.id,
            designation="Tenue DGAS",
            type_kit=ArticleKit.TypeKit.A_REMETTRE,
        )

        self.assertEqual(
            acteur_peut.call_args.args[1],
            "creer_article_kit_a_remettre",
        )
        self.assertIsNone(
            acteur_peut.call_args.kwargs["centre_id"]
        )

    @patch("kits.service.ControleAccesService.acteur_peut")
    def test_creation_a_apporter_utilise_permission_centre(
        self,
        acteur_peut,
    ):
        self.agent.is_superuser = False
        self.agent.save(update_fields=["is_superuser"])
        acteur_peut.return_value = SimpleNamespace(
            autorise=True,
            affectation=None,
            motif="",
        )

        ArticleKitService.creer(
            acteur=self.agent,
            session_id=self.session.id,
            centre_id=self.centre.id,
            designation="Chaussures centre",
            type_kit=ArticleKit.TypeKit.A_APPORTER,
        )

        self.assertEqual(
            acteur_peut.call_args.args[1],
            "creer_article_kit_a_apporter",
        )
        self.assertEqual(
            acteur_peut.call_args.kwargs["centre_id"],
            self.centre.id,
        )

    def test_preparation_individuelle_cree_lignes_non_remises(self):
        self.creer_article(designation="Badge")
        self.creer_article(
            designation="Carnet",
            quantite=2,
        )

        resultat = RemiseKitService.preparer_remise_immerge(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
        )

        self.assertEqual(resultat["remises_creees"], 2)
        self.assertEqual(
            RemiseKit.objects.filter(
                affectation_centre=self.affectation_1,
                statut_remise=RemiseKit.StatutRemise.NON_REMIS,
            ).count(),
            2,
        )

    def test_preparation_est_idempotente(self):
        self.creer_article()

        premiere = RemiseKitService.preparer_remise_immerge(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
        )
        seconde = RemiseKitService.preparer_remise_immerge(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
        )

        self.assertEqual(premiere["remises_creees"], 1)
        self.assertEqual(seconde["remises_creees"], 0)
        self.assertEqual(seconde["remises_existantes"], 1)

    def test_enregistrement_article_calcule_partiel(self):
        article = self.creer_article(quantite=3)

        remise = RemiseKitService.enregistrer_remise_article(
            affectation_centre_id=self.affectation_1.id,
            article_kit_id=article.id,
            quantite_remise=1,
            acteur=self.agent,
        )

        self.assertEqual(
            remise.statut_remise,
            RemiseKit.StatutRemise.PARTIEL,
        )

    def test_validation_complete_valide_tous_les_articles(self):
        self.creer_article(designation="Badge")
        self.creer_article(designation="Carnet")

        resultat = (
            RemiseKitService.valider_remise_complete_immerge(
                affectation_centre_id=self.affectation_1.id,
                acteur=self.agent,
            )
        )

        self.assertEqual(resultat["remises_validees"], 2)
        self.assertEqual(
            RemiseKit.objects.filter(
                affectation_centre=self.affectation_1,
                statut_remise=RemiseKit.StatutRemise.REMIS,
            ).count(),
            2,
        )
        self.assertEqual(
            resultat["statut_global"]["statut"],
            RemiseKitService.STATUT_COMPLETE,
        )

    def test_statut_global_non_commence_sans_validation(self):
        self.creer_article()
        RemiseKitService.preparer_remise_immerge(
            affectation_centre_id=self.affectation_1.id,
            acteur=self.agent,
        )

        resultat = RemiseKitService.calculer_statut_global(
            self.affectation_1.id
        )

        self.assertEqual(
            resultat["statut"],
            RemiseKitService.STATUT_NON_COMMENCEE,
        )

    def test_preparation_masse_traite_plusieurs_immerges(self):
        self.creer_article()

        resultat = RemiseKitService.preparer_pour_affectations(
            session_id=self.session.id,
            centre_id=self.centre.id,
            affectation_centre_ids=[
                self.affectation_1.id,
                self.affectation_2.id,
            ],
            acteur=self.agent,
        )

        self.assertEqual(resultat.traites, 2)
        self.assertEqual(resultat.remises_creees, 2)

    def test_visite_active_sans_resultat_bloque_remise(self):
        self.parametres.visite_medicale_active = True
        self.parametres.save(
            update_fields=[
                "visite_medicale_active",
                "updated_at",
            ]
        )
        self.creer_article()

        with self.assertRaises(ValidationKitErreur):
            RemiseKitService.preparer_remise_immerge(
                affectation_centre_id=self.affectation_1.id,
                acteur=self.agent,
            )

    def test_visite_apte_autorise_remise(self):
        self.parametres.visite_medicale_active = True
        self.parametres.save(
            update_fields=[
                "visite_medicale_active",
                "updated_at",
            ]
        )
        self.creer_visite_apte(self.affectation_1)
        self.creer_article()

        decision = EligibiliteRemiseKitService.exiger(
            self.affectation_1.id
        )

        self.assertTrue(decision["autorise_remise_kit"])


@override_settings(CACHES=CACHE_TEST)
class TachesKitsTests(KitsFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.creer_socle(visite_medicale_active=False)
        self.affectation_1 = self.creer_affectation(1)
        self.affectation_2 = self.creer_affectation(2)
        self.article = self.creer_article()

    def test_progression_est_enregistree_dans_cache(self):
        ProgressionKitsService.definir(
            "task-test",
            operation="preparation",
            statut=ProgressionKitsService.STATUT_EN_COURS,
            progression=45,
            total_immerges=10,
            immerges_traites=4,
        )

        progression = ProgressionKitsService.lire("task-test")

        self.assertEqual(progression["progression"], 45)
        self.assertEqual(progression["immerges_traites"], 4)

    def test_verrou_refuse_operation_concurrente(self):
        with ProgressionKitsService.verrou(
            "preparation",
            session_id=self.session.id,
            centre_id=self.centre.id,
            portee="meme-lot",
        ) as premier:
            with ProgressionKitsService.verrou(
                "preparation",
                session_id=self.session.id,
                centre_id=self.centre.id,
                portee="meme-lot",
            ) as second:
                self.assertTrue(premier)
                self.assertFalse(second)

    def test_tache_preparation_cree_remises(self):
        resultat_celery = preparer_remises_centre_task.apply(
            kwargs={
                "session_id": self.session.id,
                "centre_id": self.centre.id,
                "acteur_id": self.agent.id,
                "affectation_centre_ids": [
                    self.affectation_1.id,
                    self.affectation_2.id,
                ],
            }
        )
        resultat = resultat_celery.get(propagate=True)

        self.assertTrue(resultat["ok"])
        self.assertEqual(resultat["remises_creees"], 2)

    def test_tache_validation_marque_remises_completes(self):
        resultat_celery = valider_remises_immerges_task.apply(
            kwargs={
                "session_id": self.session.id,
                "centre_id": self.centre.id,
                "acteur_id": self.agent.id,
                "affectation_centre_ids": [
                    self.affectation_1.id,
                    self.affectation_2.id,
                ],
            }
        )
        resultat = resultat_celery.get(propagate=True)

        self.assertTrue(resultat["ok"])
        self.assertEqual(resultat["remises_validees"], 2)
        self.assertEqual(
            RemiseKit.objects.filter(
                statut_remise=RemiseKit.StatutRemise.REMIS,
            ).count(),
            2,
        )


class PermissionsRoutesSeedKitsTests(SimpleTestCase):
    def test_permissions_api_correspondent_aux_actions(self):
        self.assertEqual(
            PermissionArticleKit.action_permission_map["list"],
            "consulter_articles_kit",
        )
        self.assertEqual(
            PermissionRemiseKit.action_permission_map[
                "valider_complete"
            ],
            "enregistrer_remise_kit",
        )
        self.assertEqual(
            PermissionOperationKits.action_permission_map[
                "valider_masse"
            ],
            "valider_remises_kit_masse",
        )

    def test_routes_principales_sont_resolues(self):
        attentes = {
            "/api/kits/articles/": (
                "kits:articles-kit-list"
            ),
            "/api/kits/remises/": (
                "kits:remises-kit-list"
            ),
            "/api/kits/remises/valider-complete/": (
                "kits:remises-kit-valider-complete"
            ),
            "/api/kits/operations/preparer-masse/": (
                "kits:operations-kit-preparer-masse"
            ),
            "/api/kits/operations/task-123/": (
                "kits:operations-kit-detail"
            ),
        }

        for chemin, nom_vue in attentes.items():
            with self.subTest(chemin=chemin):
                self.assertEqual(resolve(chemin).view_name, nom_vue)

    def test_reverse_route_articles(self):
        self.assertEqual(
            reverse("kits:articles-kit-list"),
            "/api/kits/articles/",
        )

    def test_permissions_kits_sont_dans_seed(self):
        codes_seed = {
            definition.code
            for definition in PERMISSIONS_SYSTEME
            if definition.module == "kits"
        }
        codes_attendus = {
            "consulter_articles_kit",
            "creer_article_kit_a_remettre",
            "creer_article_kit_a_apporter",
            "modifier_article_kit",
            "desactiver_article_kit",
            "reactiver_article_kit",
            "supprimer_article_kit",
            "consulter_remises_kit",
            "enregistrer_remise_kit",
            "annuler_remise_kit",
            "consulter_statistiques_kits",
            "preparer_remises_kit_masse",
            "valider_remises_kit_masse",
            "annuler_remises_kit_masse",
            "consulter_progression_kits",
        }

        self.assertEqual(codes_seed, codes_attendus)


class ApiKitsTests(KitsFixtureMixin, TestCase):
    def setUp(self):
        self.creer_socle(visite_medicale_active=False)
        self.affectation = self.creer_affectation(1)
        self.client = APIClient()
        self.client.force_authenticate(self.agent)

    def test_creation_article_par_api(self):
        reponse = self.client.post(
            "/api/kits/articles/",
            {
                "session_id": self.session.id,
                "designation": "Badge API",
                "type_kit": "A_REMETTRE",
                "quantite": 1,
                "unite": "unité",
            },
            format="json",
        )

        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(
            reponse.data["designation"],
            "Badge API",
        )

    def test_liste_articles_exige_et_accepte_perimetre(self):
        self.creer_article()

        reponse = self.client.get(
            "/api/kits/articles/",
            {"session_id": self.session.id},
        )

        self.assertEqual(reponse.status_code, 200)

    @patch("kits.views.preparer_remises_centre_task.delay")
    def test_api_lance_preparation_celery(self, delay):
        delay.return_value = SimpleNamespace(id="task-kits-123")

        reponse = self.client.post(
            "/api/kits/operations/preparer-masse/",
            {
                "session_id": self.session.id,
                "centre_id": self.centre.id,
                "affectation_centre_ids": [
                    self.affectation.id
                ],
            },
            format="json",
        )

        self.assertEqual(reponse.status_code, 202)
        self.assertEqual(
            reponse.data["task_id"],
            "task-kits-123",
        )

    def test_api_refuse_utilisateur_non_authentifie(self):
        client = APIClient()

        reponse = client.get(
            "/api/kits/articles/",
            {"session_id": self.session.id},
        )

        self.assertIn(reponse.status_code, {401, 403})
