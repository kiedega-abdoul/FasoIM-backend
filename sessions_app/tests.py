from datetime import date

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

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
        )
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

    def test_creer_session_avec_parametres(self):
        payload = {
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
            "parametres": {
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
            },
        }

        reponse = self.client.post("/api/sessions/sessions/", payload, format="json")

        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED, reponse.data)
        self.assertEqual(SessionImmersion.objects.count(), 1)
        self.assertEqual(ParametreSession.objects.count(), 1)
        self.assertTrue(reponse.data.get("code"))
        self.assertEqual(reponse.data["statut"], SessionImmersion.Statut.BROUILLON)
        self.assertEqual(reponse.data["parametres"]["mode_entree"], ParametreSession.ModeEntree.MIXTE)

        self.assert_champs_techniques_absents(self, reponse.data)
        self.assert_champs_techniques_absents(self, reponse.data["parametres"])

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
