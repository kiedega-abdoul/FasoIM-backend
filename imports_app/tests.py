from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from sessions_app.models import ParametreSession, SessionImmersion

from .models import ErreurImport, ImportOfficiel, LigneImport
from .repository import ImportOfficielRepository
from .service import ImportOfficielService, LigneImportService, ValidationImportService


class ImportsAppServiceTests(TestCase):
    def setUp(self):
        self.session_bac = self.creer_session(
            nom="Session BAC",
            type_session=SessionImmersion.TypeSession.EXAMEN,
            public_cible=SessionImmersion.PublicCible.BAC,
            mode_entree=ParametreSession.ModeEntree.IMPORT,
        )

    def creer_session(self, *, nom, type_session, public_cible, mode_entree):
        session = SessionImmersion.objects.create(
            nom=nom,
            annee=2026,
            numero_promotion=2,
            type_session=type_session,
            public_cible=public_cible,
            date_debut=date.today() + timedelta(days=30),
            date_fin=date.today() + timedelta(days=60),
            statut=SessionImmersion.Statut.BROUILLON,
        )
        ParametreSession.objects.create(session=session, mode_entree=mode_entree)
        return session

    @staticmethod
    def fichier_csv(nom="bac.csv", contenu=None):
        contenu = contenu or "numero pv,nom,prenoms,sexe,email,telephone,date naissance\n001,OUEDRAOGO,Ali,M,ali@example.com,70000000,2004-01-01\n"
        return SimpleUploadedFile(nom, contenu.encode("utf-8"), content_type="text/csv")

    def creer_import(self, **kwargs):
        valeurs = {
            "session": self.session_bac,
            "type_source": ImportOfficiel.TypeSource.BAC,
            "fichier": self.fichier_csv(),
            "lancer_async": False,
        }
        valeurs.update(kwargs)
        return ImportOfficielService.creer_import_officiel(**valeurs)

    def test_import_compatible_avec_session(self):
        import_officiel = self.creer_import()
        self.assertEqual(import_officiel.session, self.session_bac)
        self.assertEqual(import_officiel.type_source, ImportOfficiel.TypeSource.BAC)
        self.assertEqual(import_officiel.statut, ImportOfficiel.Statut.RECU)

    def test_import_incompatible_refuse(self):
        with self.assertRaises(ValidationError):
            self.creer_import(type_source=ImportOfficiel.TypeSource.BEPC)

    def test_session_sans_mode_import_refuse(self):
        session = self.creer_session(
            nom="Session volontaire",
            type_session=SessionImmersion.TypeSession.VOLONTAIRE,
            public_cible=SessionImmersion.PublicCible.VOLONTAIRE,
            mode_entree=ParametreSession.ModeEntree.INSCRIPTION,
        )
        with self.assertRaises(ValidationError):
            self.creer_import(
                session=session,
                type_source=ImportOfficiel.TypeSource.VOLONTAIRES_ACCEPTES,
            )

    def test_fichier_doublon_avertit_puis_peut_etre_force(self):
        self.creer_import()
        with self.assertRaises(ValidationError) as contexte:
            self.creer_import(fichier=self.fichier_csv())
        self.assertIn("FICHIER_DEJA_IMPORTE", str(contexte.exception))

        second = self.creer_import(
            fichier=self.fichier_csv(),
            continuer_malgre_doublon=True,
        )
        self.assertEqual(ImportOfficiel.objects.count(), 2)
        self.assertIsNotNone(second.id)

    def test_annulation_refusee_apres_confirmation_ou_fin(self):
        import_officiel = self.creer_import()
        import_officiel.statut = ImportOfficiel.Statut.CONFIRMATION_EN_COURS
        import_officiel.save(update_fields=["statut", "updated_at"])
        with self.assertRaises(ValidationError):
            ImportOfficielService.annuler(import_officiel.id)

        import_officiel.statut = ImportOfficiel.Statut.TERMINE
        import_officiel.save(update_fields=["statut", "updated_at"])
        with self.assertRaises(ValidationError):
            ImportOfficielService.annuler(import_officiel.id)

    def test_confirmation_exige_import_valide_sans_erreur(self):
        import_officiel = self.creer_import()
        with self.assertRaises(ValidationError):
            ImportOfficielService.verifier_confirmation(import_officiel)

        ligne = LigneImport.objects.create(
            import_officiel=import_officiel,
            numero_ligne=2,
            donnees_normalisees={"numero_pv": "001", "nom": "A", "prenoms": "B"},
            statut=LigneImport.Statut.VALIDE,
        )
        import_officiel.statut = ImportOfficiel.Statut.VALIDE
        import_officiel.lignes_valides = 1
        import_officiel.save(update_fields=["statut", "lignes_valides", "updated_at"])
        self.assertEqual(ImportOfficielService.verifier_confirmation(import_officiel), import_officiel)

        ErreurImport.objects.create(
            import_officiel=import_officiel,
            ligne_import=ligne,
            type_erreur=ErreurImport.TypeErreur.INCOHERENCE,
            gravite=ErreurImport.Gravite.BLOQUANTE,
            message="Erreur bloquante",
        )
        with self.assertRaises(ValidationError):
            ImportOfficielService.verifier_confirmation(import_officiel)

    def test_suppression_refusee_pour_import_termine_ou_ayant_cree_des_donnees(self):
        import_officiel = self.creer_import()
        import_officiel.statut = ImportOfficiel.Statut.TERMINE
        import_officiel.save(update_fields=["statut", "updated_at"])
        with self.assertRaises(ValidationError):
            ImportOfficielService.verifier_suppression(import_officiel)

        import_officiel.statut = ImportOfficiel.Statut.VALIDE
        import_officiel.lignes_importees = 1
        import_officiel.save(update_fields=["statut", "lignes_importees", "updated_at"])
        with self.assertRaises(ValidationError):
            ImportOfficielService.verifier_suppression(import_officiel)

    def test_validation_formats_email_telephone_date_et_annee(self):
        erreurs = ValidationImportService._valider_donnees(
            ImportOfficiel.TypeSource.BAC,
            {
                "numero_pv": "001",
                "nom": "OUEDRAOGO",
                "prenoms": "Ali",
                "sexe": "X",
                "email": "email-invalide",
                "telephone": "12",
                "date_naissance": "31/02/2020",
                "annee_obtention": "2200",
            },
        )
        champs = {erreur["champ_cible"] for erreur in erreurs}
        self.assertTrue({"sexe", "email", "telephone", "date_naissance", "annee_obtention"}.issubset(champs))

    def test_correction_remet_ligne_en_attente_et_import_a_revalider(self):
        import_officiel = self.creer_import()
        import_officiel.statut = ImportOfficiel.Statut.VALIDE_AVEC_ERREURS
        import_officiel.save(update_fields=["statut", "updated_at"])
        ligne = LigneImport.objects.create(
            import_officiel=import_officiel,
            numero_ligne=2,
            donnees_normalisees={"numero_pv": "001"},
            statut=LigneImport.Statut.ERREUR,
        )
        ErreurImport.objects.create(
            import_officiel=import_officiel,
            ligne_import=ligne,
            type_erreur=ErreurImport.TypeErreur.CHAMP_OBLIGATOIRE,
            message="Nom absent",
        )

        ligne = LigneImportService.corriger(
            ligne.id,
            {"numero_pv": "001", "nom": "OUEDRAOGO", "prenoms": "Ali"},
        )
        import_officiel.refresh_from_db()
        self.assertEqual(ligne.statut, LigneImport.Statut.EN_ATTENTE)
        self.assertEqual(import_officiel.statut, ImportOfficiel.Statut.CORRESPONDANCE_VALIDEE)
        self.assertFalse(ligne.erreurs.filter(deleted_at__isnull=True).exists())

    def test_ligne_importee_ne_peut_etre_corrigee_ni_ignoree(self):
        import_officiel = self.creer_import()
        ligne = LigneImport.objects.create(
            import_officiel=import_officiel,
            numero_ligne=2,
            statut=LigneImport.Statut.IMPORTEE,
        )
        with self.assertRaises(ValidationError):
            LigneImportService.corriger(ligne.id, {"nom": "Test"})
        with self.assertRaises(ValidationError):
            LigneImportService.ignorer(ligne.id)

    def test_statistiques_recalculees_apres_ignorance(self):
        import_officiel = self.creer_import()
        import_officiel.statut = ImportOfficiel.Statut.VALIDE_AVEC_ERREURS
        import_officiel.save(update_fields=["statut", "updated_at"])
        ligne = LigneImport.objects.create(
            import_officiel=import_officiel,
            numero_ligne=2,
            statut=LigneImport.Statut.ERREUR,
        )
        LigneImportService.ignorer(ligne.id, "Ligne non exploitable")
        import_officiel.refresh_from_db()
        self.assertEqual(import_officiel.lignes_ignorees, 1)
        self.assertEqual(import_officiel.lignes_erreur, 0)
        self.assertEqual(import_officiel.statut, ImportOfficiel.Statut.VALIDE)

    def test_repository_hash_restreint_aux_imports_non_supprimes(self):
        import_officiel = self.creer_import()
        self.assertEqual(ImportOfficielRepository.lister_par_hash(import_officiel.hash_fichier).count(), 1)
        import_officiel.deleted_at = timezone.now()
        import_officiel.save(update_fields=["deleted_at", "updated_at"])
        self.assertEqual(ImportOfficielRepository.lister_par_hash(import_officiel.hash_fichier).count(), 0)
