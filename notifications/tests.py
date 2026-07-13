from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.apps import apps
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
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
from audit.models import JournalAction
from imports_app.models import ImportOfficiel
from immerges.models import Immerge, ImmergeExamen, InscriptionVolontaire
from organisation.models import RegleOrganisationCentre
from sessions_app.models import SessionImmersion

from .repository import NotificationRepository
from .service import ErreurEnvoiEmail, NotificationService, TypesMessage
from .tasks import envoyer_emails_masse_task, informer_immerges_task


LOC_MEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "notifications-tests",
    }
}


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CACHES=LOC_MEM,
    NOTIFICATIONS_TENTATIVE_TTL_SECONDS=60,
    NOTIFICATIONS_ENABLE_DURING_TESTS=True,
    NOTIFICATIONS_LOCK_SECONDS=60,
    NOTIFICATIONS_BATCH_SIZE=50,
    FASOIM_PUBLIC_URL="https://fasoim.test",
)
class NotificationsTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.session = SessionImmersion.objects.create(
            nom="Immersion 2026",
            annee=2026,
            numero_promotion=2,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=date.today() + timedelta(days=10),
            date_fin=date.today() + timedelta(days=20),
            statut=SessionImmersion.Statut.OUVERTE,
        )
        self.region = RegionImmersion.objects.create(code="CENTRE", nom="Centre")
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="CTR-001",
            nom="Centre test",
            province="Kadiogo",
            ville="Ouagadougou",
            capacite_totale=100,
        )
        self.acteur = Acteur.objects.create_user(
            username="admin.test",
            email="admin@example.com",
            first_name="Admin",
            last_name="Test",
            password="Password123!",
            statut=Acteur.Statut.ACTIF,
            is_active=True,
            is_superuser=True,
            is_staff=True,
        )

    def creer_import(self):
        return ImportOfficiel.objects.create(
            session=self.session,
            type_source=ImportOfficiel.TypeSource.BEPC,
            type_fichier=ImportOfficiel.TypeFichier.CSV,
            fichier="imports/test.csv",
            nom_fichier_original="test.csv",
        )

    def creer_immerge_examen(self, *, numero, email="", etablissement="Lycée A"):
        source = ImmergeExamen.objects.create(
            import_officiel=self.creer_import(),
            numero_ligne_import=numero,
            numero_pv=f"PV-{numero}",
            type_examen=ImmergeExamen.TypeExamen.BEPC,
            nom_et_prenoms=f"Élève {numero}",
            email=email,
            etablissement_origine=etablissement,
            statut_validation=ImmergeExamen.StatutValidation.VALIDE,
        )
        return Immerge.objects.create(
            session=self.session,
            type_immerge=Immerge.TypeImmerge.BEPC,
            origine_id=source.id,
            code_fasoim=f"IP2026BEPC02{numero:05d}",
        )

    def test_notifications_ne_cree_aucun_modele(self):
        self.assertEqual(list(apps.get_app_config("notifications").get_models()), [])

    def test_envoi_email_reussi_est_audite(self):
        resultat = NotificationService.envoyer_email(
            destinataire="dest@example.com",
            sujet="Sujet",
            message="Message",
            type_message="TEST",
            cle_evenement="EVT-1",
            acteur=self.acteur,
            session=self.session,
        )
        self.assertTrue(resultat.envoye)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            JournalAction.objects.filter(
                module_source="notifications",
                resultat=JournalAction.Resultat.SUCCES,
                contexte__cle_deduplication=resultat.cle_deduplication,
            ).exists()
        )

    def test_meme_email_meme_evenement_n_est_pas_envoye_deux_fois(self):
        premier = NotificationService.envoyer_email(
            destinataire="dest@example.com",
            sujet="Sujet",
            message="Message",
            type_message="TEST",
            cle_evenement="EVT-UNIQUE",
        )
        second = NotificationService.envoyer_email(
            destinataire="DEST@example.com",
            sujet="Sujet",
            message="Message",
            type_message="TEST",
            cle_evenement="EVT-UNIQUE",
        )
        self.assertTrue(premier.envoye)
        self.assertFalse(second.envoye)
        self.assertEqual(second.statut, NotificationService.STATUT_DEJA_ENVOYE)
        self.assertEqual(len(mail.outbox), 1)

    @patch("notifications.service.JournalActionService.journaliser_succes")
    def test_marqueur_redis_evite_doublon_si_audit_tombe_apres_envoi(self, succes):
        succes.side_effect = Exception("PostgreSQL indisponible")
        kwargs = dict(
            destinataire="fallback@example.com",
            sujet="Sujet",
            message="Message",
            type_message="TEST",
            cle_evenement="EVT-FALLBACK-AUDIT",
        )
        premier = NotificationService.envoyer_email(**kwargs)
        second = NotificationService.envoyer_email(**kwargs)
        self.assertTrue(premier.envoye)
        self.assertFalse(second.envoye)
        self.assertEqual(second.statut, NotificationService.STATUT_DEJA_ENVOYE)
        self.assertEqual(len(mail.outbox), 1)

    def test_evenement_different_autorise_un_nouvel_email(self):
        for cle in ("EVT-1", "EVT-2"):
            NotificationService.envoyer_email(
                destinataire="dest@example.com",
                sujet="Sujet",
                message="Message",
                type_message="TEST",
                cle_evenement=cle,
            )
        self.assertEqual(len(mail.outbox), 2)

    @patch("notifications.service.EmailMultiAlternatives.send")
    def test_un_echec_autorise_une_nouvelle_tentative(self, envoyer):
        envoyer.side_effect = [Exception("SMTP indisponible"), 1]
        kwargs = dict(
            destinataire="dest@example.com",
            sujet="Sujet",
            message="Message",
            type_message="TEST",
            cle_evenement="EVT-ECHEC",
        )
        with self.assertRaises(ErreurEnvoiEmail):
            NotificationService.envoyer_email(**kwargs)
        resultat = NotificationService.envoyer_email(**kwargs, tentative=2)
        self.assertTrue(resultat.envoye)
        self.assertEqual(envoyer.call_count, 2)

    @patch("notifications.service.cache.add", return_value=False)
    def test_verrou_empeche_deux_envois_concurrents(self, _):
        resultat = NotificationService.envoyer_email(
            destinataire="dest@example.com",
            sujet="Sujet",
            message="Message",
            type_message="TEST",
            cle_evenement="EVT-LOCK",
        )
        self.assertFalse(resultat.envoye)
        self.assertEqual(resultat.statut, NotificationService.STATUT_EN_COURS)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_invalide_est_refuse_et_audite(self):
        resultat = NotificationService.envoyer_email(
            destinataire="pas-un-email",
            sujet="Sujet",
            message="Message",
            type_message="TEST",
            cle_evenement="EVT-INVALIDE",
        )
        self.assertFalse(resultat.envoye)
        self.assertEqual(resultat.statut, NotificationService.STATUT_REFUSE)
        self.assertTrue(
            JournalAction.objects.filter(
                module_source="notifications",
                resultat=JournalAction.Resultat.REFUS,
                motif="ADRESSE_EMAIL_ABSENTE_OU_INVALIDE",
            ).exists()
        )

    def test_corps_email_n_est_pas_stocke_dans_audit(self):
        secret = "mot-de-passe-temporaire-tres-secret"
        NotificationService.envoyer_email(
            destinataire="dest@example.com",
            sujet="Bienvenue",
            message=f"Votre mot de passe : {secret}",
            type_message=TypesMessage.BIENVENUE_ACTEUR,
            cle_evenement="BIENVENUE-1",
        )
        journal = JournalAction.objects.filter(
            module_source="notifications",
            resultat=JournalAction.Resultat.SUCCES,
        ).latest("id")
        self.assertNotIn(secret, str(journal.contexte))
        self.assertNotIn(secret, journal.motif)

    def test_resolution_contact_immerge_direct(self):
        immerge = self.creer_immerge_examen(numero=1, email="eleve@example.com")
        contact = NotificationRepository.contact_immerge(immerge)
        self.assertEqual(contact.email, "eleve@example.com")
        self.assertEqual(contact.immerge_id, immerge.id)

    def test_relais_meme_etablissement(self):
        sans_email = self.creer_immerge_examen(numero=2, email="", etablissement="Lycée A")
        relais = self.creer_immerge_examen(numero=3, email="relais@example.com", etablissement="Lycée A")
        contacts = NotificationRepository.relais_etablissement(
            session_id=self.session.id,
            type_examen=ImmergeExamen.TypeExamen.BEPC,
            etablissement="Lycée A",
            exclure_immerge_ids=[sans_email.id],
            limite=3,
        )
        self.assertEqual([c.email for c in contacts], ["relais@example.com"])
        self.assertEqual(contacts[0].immerge_id, relais.id)

    def test_relais_ne_voit_pas_liste_des_camarades(self):
        sujet, message = NotificationService.message_relais_etablissement(
            etablissement="Lycée A",
            nombre_immerges=12,
            type_information="Affectations publiées",
            url="https://fasoim.test",
        )
        self.assertIn("12", message)
        self.assertNotIn("PV-", message)
        self.assertNotIn("code FasoIM", message)
        self.assertIn("Aucune affectation individuelle", message)

    def test_envoi_masse_deduplique_chaque_destinataire(self):
        messages = [
            {
                "destinataire": "a@example.com",
                "sujet": "Sujet",
                "message": "Message",
                "type_message": "MASS",
                "cle_evenement": "LOT-1",
            },
            {
                "destinataire": "a@example.com",
                "sujet": "Sujet",
                "message": "Message",
                "type_message": "MASS",
                "cle_evenement": "LOT-1",
            },
        ]
        resultat = envoyer_emails_masse_task.apply(args=[messages]).get()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(resultat["envoyes"], 1)
        self.assertEqual(resultat["deja_envoyes"], 1)

    def test_information_immerges_utilise_direct_et_relais(self):
        direct = self.creer_immerge_examen(numero=4, email="direct@example.com", etablissement="Lycée B")
        sans_email = self.creer_immerge_examen(numero=5, email="", etablissement="Lycée B")
        relais = self.creer_immerge_examen(numero=6, email="relais-b@example.com", etablissement="Lycée B")
        resultat = informer_immerges_task.apply(
            args=[[direct.id, sans_email.id]],
            kwargs={
                "type_message": TypesMessage.AFFECTATION_IMMERGE_PUBLIEE,
                "sujet": "Résultats disponibles",
                "message": "Consultez votre résultat.",
                "cle_evenement": "PUBLICATION-1",
                "url_portail": "https://fasoim.test",
            },
        ).get()
        self.assertEqual(resultat["envoyes_directs"], 1)
        self.assertEqual(resultat["relais_envoyes"], 2)
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(relais.id, NotificationRepository.contact_immerge(relais).immerge_id)

    def test_informer_immerges_rejoue_ne_renvoie_pas(self):
        direct = self.creer_immerge_examen(numero=7, email="direct7@example.com")
        kwargs = {
            "type_message": TypesMessage.AFFECTATION_IMMERGE_PUBLIEE,
            "sujet": "Résultats disponibles",
            "message": "Consultez votre résultat.",
            "cle_evenement": "PUBLICATION-2",
        }
        informer_immerges_task.apply(args=[[direct.id]], kwargs=kwargs).get()
        informer_immerges_task.apply(args=[[direct.id]], kwargs=kwargs).get()
        self.assertEqual(len(mail.outbox), 1)

    def test_signal_affectation_acteur_planifie_un_email(self):
        with patch("notifications.tasks.envoyer_email_task.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                AffectationActeur.objects.create(
                    acteur=self.acteur,
                    session=self.session,
                    niveau_affectation=AffectationActeur.NiveauAffectation.NATIONAL,
                    date_debut=date.today(),
                )
        self.assertEqual(delay.call_count, 1)
        payload = delay.call_args.args[0]
        self.assertEqual(payload["type_message"], TypesMessage.AFFECTATION_ACTEUR)

    def test_signal_ne_renvoie_pas_si_champ_non_important(self):
        affectation = AffectationActeur.objects.create(
            acteur=self.acteur,
            session=self.session,
            niveau_affectation=AffectationActeur.NiveauAffectation.NATIONAL,
            date_debut=date.today(),
        )
        with patch("notifications.tasks.envoyer_email_task.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                affectation.affecte_par = self.acteur
                affectation.save(update_fields=["affecte_par", "updated_at"])
        delay.assert_not_called()

    def test_signal_volontaire_reception_et_decision(self):
        with patch("notifications.tasks.envoyer_email_task.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                volontaire = InscriptionVolontaire.objects.create(
                    session=self.session,
                    code_suivi="VOL-001",
                    nom="Ouédraogo",
                    prenoms="Awa",
                    email="awa@example.com",
                    telephone="70000000",
                )
            self.assertEqual(delay.call_count, 1)
            delay.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                volontaire.statut_demande = InscriptionVolontaire.StatutDemande.ACCEPTEE
                volontaire.save(update_fields=["statut_demande", "updated_at"])
            self.assertEqual(delay.call_count, 1)

    def test_signal_organisation_prete_notifie_dgas_et_dr(self):
        regle = RegleOrganisationCentre.objects.create(
            session=self.session,
            centre=self.centre,
            seuil_division_sections=2,
            capacite_max_section=50,
            seuil_division_groupes=2,
            capacite_max_groupe=25,
            statut=RegleOrganisationCentre.Statut.BROUILLON,
        )
        with patch("notifications.tasks.notifier_acteurs_role_task.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                regle.statut = RegleOrganisationCentre.Statut.PRETE_PUBLICATION
                regle.save(update_fields=["statut", "updated_at"])
        roles = {appel.args[0] for appel in delay.call_args_list}
        self.assertEqual(roles, {"DGAS", "DIRECTEUR_REGIONAL"})

    def test_api_test_email_superuser(self):
        client = APIClient()
        client.force_authenticate(self.acteur)
        with patch("notifications.views.envoyer_email_task.delay") as delay:
            delay.return_value.id = "task-test"
            response = client.post("/api/notifications/tester-email/", {}, format="json")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["task_id"], "task-test")
        payload = delay.call_args.args[0]
        self.assertEqual(payload["destinataire"], self.acteur.email)

    def test_api_ne_propose_aucun_crud(self):
        client = APIClient()
        client.force_authenticate(self.acteur)
        self.assertEqual(client.post("/api/notifications/", {}, format="json").status_code, 404)
        self.assertEqual(client.patch("/api/notifications/1/", {}, format="json").status_code, 404)
        self.assertEqual(client.delete("/api/notifications/1/").status_code, 404)

    def test_api_statistiques(self):
        NotificationService.envoyer_email(
            destinataire="stats@example.com",
            sujet="Sujet",
            message="Message",
            type_message="STATS",
            cle_evenement="STATS-1",
            acteur=self.acteur,
        )
        client = APIClient()
        client.force_authenticate(self.acteur)
        response = client.get("/api/notifications/statistiques/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data["succes"], 1)

    def test_seed_ajoute_permissions_notifications(self):
        call_command("seed_accounts", verbosity=0)
        self.assertEqual(
            Permission.objects.filter(
                module="notifications",
                statut=Permission.Statut.ACTIVE,
                deleted_at__isnull=True,
            ).count(),
            3,
        )
        self.assertEqual(
            RolePermission.objects.filter(
                permission__module="notifications",
                deleted_at__isnull=True,
            ).count(),
            8,
        )

    def test_relance_refusee_sans_echec_precedent(self):
        client = APIClient()
        client.force_authenticate(self.acteur)
        response = client.post(
            "/api/notifications/relancer-email/",
            {
                "destinataire": "dest@example.com",
                "sujet": "Sujet",
                "message": "Message",
                "type_message": "TEST",
                "cle_evenement": "PAS-ECHEC",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_relance_autorisee_apres_echec(self):
        cle = NotificationService.construire_cle(
            destinataire="dest@example.com",
            sujet="Sujet",
            message="Message",
            type_message="TEST",
            cle_evenement="APRES-ECHEC",
        )
        JournalAction.objects.create(
            origine=JournalAction.Origine.SYSTEME,
            resultat=JournalAction.Resultat.ECHEC,
            canal=JournalAction.Canal.EMAIL,
            code_action="envoyer_email",
            module_source="notifications",
            contexte={"cle_deduplication": cle},
        )
        client = APIClient()
        client.force_authenticate(self.acteur)
        with patch("notifications.views.envoyer_email_task.delay") as delay:
            delay.return_value.id = "task-retry"
            response = client.post(
                "/api/notifications/relancer-email/",
                {
                    "destinataire": "dest@example.com",
                    "sujet": "Sujet",
                    "message": "Message",
                    "type_message": "TEST",
                    "cle_evenement": "APRES-ECHEC",
                },
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["task_id"], "task-retry")
