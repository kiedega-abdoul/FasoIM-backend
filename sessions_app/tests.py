from datetime import date, timedelta

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from django.utils import timezone

from accounts.models import AffectationActeur, AffectationRole, Permission, Role, RolePermission

from .models import ParametreSession, SessionImmersion
from .service import SessionImmersionService


CHAMPS_TECHNIQUES_NON_EXPOSES = {"created_at", "updated_at", "deleted_at"}


class SessionImmersionAPITests(APITestCase):
    """Tests API du module sessions_app."""

    def setUp(self):
        self.utilisateur = self.creer_utilisateur(
            identifiant="testeur_sessions",
            email="testeur.sessions@example.com",
            password="pass-test-123",
        )
        self.admin = self.creer_utilisateur(
            identifiant="admin_sessions",
            email="admin.sessions@example.com",
            password="pass-admin-123",
            is_staff=True,
            is_superuser=True,
        )
        self.preparer_droits_sessions(self.utilisateur)
        self.client.force_authenticate(user=self.utilisateur)

    @staticmethod
    def creer_utilisateur(identifiant, email, password, **extra_fields):
        """
        Crée un utilisateur compatible avec un User Django standard
        ou un futur modèle utilisateur personnalisé.
        """
        User = get_user_model()
        username_field = User.USERNAME_FIELD

        donnees = dict(extra_fields)
        donnees.setdefault("email", email)

        if username_field == "email":
            donnees[username_field] = email
        else:
            donnees[username_field] = identifiant

        return User.objects.create_user(password=password, **donnees)


    @staticmethod
    def preparer_droits_sessions(utilisateur):
        """Donne à un acteur de test les droits nécessaires sur sessions_app."""
        role, _ = Role.objects.get_or_create(
            code="TEST_SESSIONS",
            defaults={
                "libelle": "Test sessions",
                "description": "Rôle utilisé uniquement par les tests du module sessions_app.",
                "niveau": 10,
                "perimetre_autorise": Role.Perimetre.NATIONAL,
                "est_systeme": False,
                "est_modifiable": True,
            },
        )

        codes_permissions = [
            "lister_sessions",
            "consulter_session",
            "creer_session",
            "configurer_parametres_session",
            "modifier_session",
            "archiver_session",
            "modifier_parametres_session",
            "cloturer_session",
            "consulter_historique_sessions",
            "consulter_historique_parametres_session",
        ]
        for code in codes_permissions:
            permission, _ = Permission.objects.get_or_create(
                code=code,
                defaults={
                    "libelle": code.replace("_", " ").capitalize(),
                    "module": "sessions_app",
                    "description": "Permission créée pour les tests sessions_app.",
                    "est_systeme": True,
                },
            )
            RolePermission.objects.get_or_create(
                role=role,
                permission=permission,
                defaults={"est_delegable": True, "perimetre_delegation_max": Role.Perimetre.NATIONAL},
            )

        affectation, _ = AffectationActeur.objects.get_or_create(
            acteur=utilisateur,
            niveau_affectation=AffectationActeur.NiveauAffectation.NATIONAL,
            defaults={"statut": AffectationActeur.Statut.ACTIVE},
        )
        AffectationRole.objects.get_or_create(affectation_acteur=affectation, role=role)

    @staticmethod
    def extraire_liste(reponse):
        """Gère les réponses paginées et non paginées."""
        donnees = reponse.data
        if isinstance(donnees, dict) and "results" in donnees:
            return donnees["results"]
        return donnees

    @staticmethod
    def assert_champs_techniques_absents(testcase, donnees):
        testcase.assertTrue(isinstance(donnees, dict))
        testcase.assertFalse(
            CHAMPS_TECHNIQUES_NON_EXPOSES.intersection(donnees.keys()),
            "Les champs internes created_at, updated_at ou deleted_at ne doivent pas être exposés.",
        )

    def creer_session(self, nom, annee, type_session, public_cible, mode_entree, **options):
        session_data = {
            "nom": nom,
            "annee": annee,
            "numero_promotion": options.pop("numero_promotion", 2),
            "type_session": type_session,
            "public_cible": public_cible,
            "date_debut": options.pop("date_debut", date(2026, 8, 1)),
            "date_fin": options.pop("date_fin", date(2026, 8, 30)),
            "date_ouverture_inscription": options.pop(
                "date_ouverture_inscription",
                date(2026, 7, 1),
            ),
            "date_fermeture_inscription": options.pop(
                "date_fermeture_inscription",
                date(2026, 7, 31),
            ),
            "description": options.pop("description", "Session créée pour les tests API."),
        }
        parametres_data = {
            "mode_entree": mode_entree,
            "hebergement_active": options.pop("hebergement_active", True),
            "repas_active": options.pop("repas_active", True),
            "visite_medicale_active": options.pop("visite_medicale_active", False),
            "evaluation_active": options.pop("evaluation_active", False),
            "attestation_active": options.pop("attestation_active", True),
            "consultation_publique_active": options.pop(
                "consultation_publique_active",
                True,
            ),
            "directives_generales": options.pop("directives_generales", "Respecter les consignes."),
            "consignes_generales": options.pop("consignes_generales", "Arriver à l'heure."),
            "documents_exiges": options.pop("documents_exiges", ["CNIB"]),
        }

        if options:
            raise AssertionError(f"Options de test non utilisées : {options}")

        return SessionImmersionService.creer_session_avec_parametres(
            session_data=session_data,
            parametres_data=parametres_data,
        )

    def test_creer_session_puis_configurer_parametres(self):
        payload_session = {
            "nom": "Session BAC 2026",
            "annee": 2026,
            "numero_promotion": 2,
            "type_session": SessionImmersion.TypeSession.EXAMEN,
            "public_cible": SessionImmersion.PublicCible.BAC,
            "date_debut": "2026-08-01",
            "date_fin": "2026-08-30",
            "date_ouverture_inscription": "2026-07-01",
            "date_fermeture_inscription": "2026-07-31",
            "description": "Session BAC créée depuis l'API.",
        }

        reponse_session = self.client.post(
            "/api/sessions/sessions/",
            payload_session,
            format="json",
        )

        self.assertEqual(reponse_session.status_code, status.HTTP_201_CREATED, reponse_session.data)
        self.assertEqual(SessionImmersion.objects.count(), 1)
        self.assertEqual(ParametreSession.objects.count(), 0)
        self.assertTrue(reponse_session.data.get("code"))
        self.assertEqual(reponse_session.data["statut"], SessionImmersion.Statut.BROUILLON)
        self.assertNotIn("parametres", reponse_session.data)
        self.assert_champs_techniques_absents(self, reponse_session.data)

        payload_parametres = {
            "session": reponse_session.data["id"],
            "mode_entree": ParametreSession.ModeEntree.MIXTE,
            "hebergement_active": True,
            "repas_active": True,
            "visite_medicale_active": True,
            "evaluation_active": False,
            "attestation_active": True,
            "consultation_publique_active": True,
            "taux_presence_minimum_attestation": "80.00",
            "directives_generales": "Se présenter avec une pièce d'identité.",
            "consignes_generales": "Respect strict du règlement intérieur.",
            "documents_exiges": ["CNIB", "Convocation"],
        }
        reponse_parametres = self.client.post(
            "/api/sessions/parametres/",
            payload_parametres,
            format="json",
        )

        self.assertEqual(
            reponse_parametres.status_code,
            status.HTTP_201_CREATED,
            reponse_parametres.data,
        )
        self.assertEqual(ParametreSession.objects.count(), 1)
        self.assertEqual(
            reponse_parametres.data["mode_entree"],
            ParametreSession.ModeEntree.MIXTE,
        )
        self.assert_champs_techniques_absents(self, reponse_parametres.data)

    def test_lister_sessions_et_filtrer_par_champs_session_et_parametres(self):
        session_bac = self.creer_session(
            nom="Session BAC 2026",
            annee=2026,
            type_session=SessionImmersion.TypeSession.EXAMEN,
            public_cible=SessionImmersion.PublicCible.BAC,
            mode_entree=ParametreSession.ModeEntree.MIXTE,
            hebergement_active=True,
        )
        self.creer_session(
            nom="Session volontaires 2027",
            annee=2027,
            type_session=SessionImmersion.TypeSession.VOLONTAIRE,
            public_cible=SessionImmersion.PublicCible.VOLONTAIRE,
            mode_entree=ParametreSession.ModeEntree.INSCRIPTION,
            hebergement_active=False,
            numero_promotion=3,
            date_debut=date(2027, 8, 1),
            date_fin=date(2027, 8, 30),
            date_ouverture_inscription=date(2027, 7, 1),
            date_fermeture_inscription=date(2027, 7, 31),
        )

        reponse = self.client.get(
            "/api/sessions/sessions/",
            {
                "annee": "2026",
                "type_session": SessionImmersion.TypeSession.EXAMEN,
                "public_cible": SessionImmersion.PublicCible.BAC,
                "mode_entree": ParametreSession.ModeEntree.MIXTE,
                "hebergement_active": "true",
            },
        )

        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        resultats = self.extraire_liste(reponse)
        self.assertEqual(len(resultats), 1)
        self.assertEqual(resultats[0]["id"], session_bac.id)

    def test_consulter_parametres_associes_a_une_session(self):
        session = self.creer_session(
            nom="Session mixte 2026",
            annee=2026,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            mode_entree=ParametreSession.ModeEntree.MIXTE,
        )

        reponse = self.client.get(f"/api/sessions/sessions/{session.id}/parametres/")

        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.assertEqual(reponse.data["mode_entree"], ParametreSession.ModeEntree.MIXTE)
        self.assertTrue(reponse.data["utilise_import"])
        self.assertTrue(reponse.data["utilise_inscription_volontaire"])
        self.assert_champs_techniques_absents(self, reponse.data)

    def test_action_ouvrir_session(self):
        session = self.creer_session(
            nom="Session à ouvrir",
            annee=2026,
            type_session=SessionImmersion.TypeSession.EXAMEN,
            public_cible=SessionImmersion.PublicCible.BEPC,
            mode_entree=ParametreSession.ModeEntree.IMPORT,
        )

        reponse = self.client.post(f"/api/sessions/sessions/{session.id}/ouvrir/")

        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.assertEqual(reponse.data["statut"], SessionImmersion.Statut.OUVERTE)
        session.refresh_from_db()
        self.assertEqual(session.statut, SessionImmersion.Statut.OUVERTE)

    def test_suppression_logique_cache_la_session_des_listes_normales(self):
        session = self.creer_session(
            nom="Session à supprimer",
            annee=2026,
            type_session=SessionImmersion.TypeSession.EXAMEN,
            public_cible=SessionImmersion.PublicCible.BAC,
            mode_entree=ParametreSession.ModeEntree.IMPORT,
        )

        reponse_suppression = self.client.delete(f"/api/sessions/sessions/{session.id}/")
        self.assertEqual(reponse_suppression.status_code, status.HTTP_204_NO_CONTENT, reponse_suppression.data)

        session.refresh_from_db()
        self.assertIsNotNone(session.deleted_at)
        self.assertTrue(session.code.startswith("DEL-"))

        reponse_liste = self.client.get("/api/sessions/sessions/")
        self.assertEqual(reponse_liste.status_code, status.HTTP_200_OK, reponse_liste.data)
        ids = [element["id"] for element in self.extraire_liste(reponse_liste)]
        self.assertNotIn(session.id, ids)

    def test_historique_reserve_aux_administrateurs(self):
        session = self.creer_session(
            nom="Session historique",
            annee=2026,
            type_session=SessionImmersion.TypeSession.EXAMEN,
            public_cible=SessionImmersion.PublicCible.BAC,
            mode_entree=ParametreSession.ModeEntree.IMPORT,
        )

        reponse = self.client.get("/api/sessions/sessions/historique/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)

    def test_transition_invalide_est_refusee(self):
        session = self.creer_session(
            nom="Session transition", annee=2026,
            type_session=SessionImmersion.TypeSession.EXAMEN,
            public_cible=SessionImmersion.PublicCible.BAC,
            mode_entree=ParametreSession.ModeEntree.IMPORT,
        )
        reponse = self.client.post(f"/api/sessions/sessions/{session.id}/demarrer/")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST, reponse.data)
        session.refresh_from_db()
        self.assertEqual(session.statut, SessionImmersion.Statut.BROUILLON)

    def test_annulation_exige_un_motif_et_conserve_la_session(self):
        session = self.creer_session(
            nom="Session annulation", annee=2026,
            type_session=SessionImmersion.TypeSession.VOLONTAIRE,
            public_cible=SessionImmersion.PublicCible.VOLONTAIRE,
            mode_entree=ParametreSession.ModeEntree.INSCRIPTION,
        )
        sans_motif = self.client.post(f"/api/sessions/sessions/{session.id}/annuler/", {}, format="json")
        self.assertEqual(sans_motif.status_code, status.HTTP_400_BAD_REQUEST)
        reponse = self.client.post(
            f"/api/sessions/sessions/{session.id}/annuler/",
            {"motif": "Décision officielle."}, format="json",
        )
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        session.refresh_from_db()
        self.assertEqual(session.statut, SessionImmersion.Statut.ANNULEE)
        self.assertIsNone(session.deleted_at)
        self.assertEqual(session.motif_annulation, "Décision officielle.")

    def test_parametres_ne_peuvent_pas_etre_supprimes_directement(self):
        session = self.creer_session(
            nom="Session paramètres", annee=2026,
            type_session=SessionImmersion.TypeSession.EXAMEN,
            public_cible=SessionImmersion.PublicCible.BEPC,
            mode_entree=ParametreSession.ModeEntree.IMPORT,
        )
        reponse = self.client.delete(f"/api/sessions/parametres/{session.parametres.id}/")
        self.assertEqual(reponse.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_public_cible_incoherent_est_refuse(self):
        payload = {
            "nom": "Session incohérente", "annee": 2026,
            "type_session": SessionImmersion.TypeSession.CONCOURS,
            "public_cible": SessionImmersion.PublicCible.MIXTE,
            "date_debut": "2026-08-01", "date_fin": "2026-08-30",
        }
        reponse = self.client.post("/api/sessions/sessions/", payload, format="json")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST, reponse.data)

    def test_route_publique_expose_seulement_les_informations_utiles(self):
        aujourd_hui = timezone.localdate()
        session = self.creer_session(
            nom="Session volontaire publique", annee=aujourd_hui.year,
            type_session=SessionImmersion.TypeSession.VOLONTAIRE,
            public_cible=SessionImmersion.PublicCible.VOLONTAIRE,
            mode_entree=ParametreSession.ModeEntree.INSCRIPTION,
            date_debut=aujourd_hui + timedelta(days=10),
            date_fin=aujourd_hui + timedelta(days=40),
            date_ouverture_inscription=aujourd_hui - timedelta(days=1),
            date_fermeture_inscription=aujourd_hui + timedelta(days=5),
        )
        SessionImmersionService.ouvrir_session(session)
        self.client.force_authenticate(user=None)
        reponse = self.client.get("/api/sessions/public/ouvertes-inscription/")
        self.assertEqual(reponse.status_code, status.HTTP_200_OK, reponse.data)
        self.assertEqual(len(reponse.data), 1)
        donnees = reponse.data[0]
        self.assertEqual(donnees["id"], session.id)
        self.assertNotIn("parametres", donnees)
        self.assertNotIn("statut", donnees)
        self.assertNotIn("taux_presence_minimum_attestation", donnees)

    def test_une_seule_session_active_par_type(self):
        premiere = self.creer_session(
            nom="Session volontaire active 1",
            annee=2026,
            type_session=SessionImmersion.TypeSession.VOLONTAIRE,
            public_cible=SessionImmersion.PublicCible.VOLONTAIRE,
            mode_entree=ParametreSession.ModeEntree.INSCRIPTION,
        )
        seconde = self.creer_session(
            nom="Session volontaire active 2",
            annee=2027,
            type_session=SessionImmersion.TypeSession.VOLONTAIRE,
            public_cible=SessionImmersion.PublicCible.VOLONTAIRE,
            mode_entree=ParametreSession.ModeEntree.INSCRIPTION,
            date_debut=date(2027, 8, 1),
            date_fin=date(2027, 8, 30),
            date_ouverture_inscription=date(2027, 7, 1),
            date_fermeture_inscription=date(2027, 7, 31),
        )

        SessionImmersionService.ouvrir_session(premiere)
        with self.assertRaisesMessage(Exception, "Une autre session active existe déjà"):
            SessionImmersionService.mettre_en_preparation(seconde)

        seconde.refresh_from_db()
        self.assertEqual(seconde.statut, SessionImmersion.Statut.BROUILLON)

    def test_une_seule_session_publique_pour_les_volontaires(self):
        aujourd_hui = timezone.localdate()
        session_volontaire = self.creer_session(
            nom="Session volontaire publique unique",
            annee=aujourd_hui.year,
            type_session=SessionImmersion.TypeSession.VOLONTAIRE,
            public_cible=SessionImmersion.PublicCible.VOLONTAIRE,
            mode_entree=ParametreSession.ModeEntree.INSCRIPTION,
            date_debut=aujourd_hui + timedelta(days=10),
            date_fin=aujourd_hui + timedelta(days=40),
            date_ouverture_inscription=aujourd_hui - timedelta(days=1),
            date_fermeture_inscription=aujourd_hui + timedelta(days=5),
        )
        session_mixte = self.creer_session(
            nom="Session mixte concurrente",
            annee=aujourd_hui.year + 1,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            mode_entree=ParametreSession.ModeEntree.MIXTE,
            date_debut=aujourd_hui + timedelta(days=50),
            date_fin=aujourd_hui + timedelta(days=80),
            date_ouverture_inscription=aujourd_hui - timedelta(days=1),
            date_fermeture_inscription=aujourd_hui + timedelta(days=5),
        )

        SessionImmersionService.ouvrir_session(session_volontaire)
        with self.assertRaisesMessage(Exception, "demandes volontaires"):
            SessionImmersionService.ouvrir_session(session_mixte)
