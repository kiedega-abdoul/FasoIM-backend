from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.db import models
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from imports_app.models import ImportOfficiel, LigneImport
from immerges.models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
)
from immerges.service import ImportVersImmergeService
from sessions_app.models import SessionImmersion


class ImmergesImportBridgeTests(TestCase):
    """Tests du pont réel imports_app → immerges.

    Ces tests vérifient qu'une LigneImport validée devient bien :
    - une source métier dans immerges ;
    - puis une ligne centrale Immerge avec code FasoIM et QR code.
    """

    def creer_session(self):
        """Crée une session de test sans dépendre fortement du détail du modèle."""

        valeurs_connues = {
            "code": f"TST-{uuid4().hex[:8]}",
            "nom": "Session test",
            "libelle": "Session test",
            "intitule": "Session test",
            "description": "Session utilisée pour les tests.",
            "annee": 2026,
            "numero_promotion": 2,
            "date_debut": timezone.now().date(),
            "date_fin": timezone.now().date() + timedelta(days=30),
        }

        kwargs = {}

        for field in SessionImmersion._meta.fields:
            if field.primary_key or field.auto_created:
                continue

            if field.name in valeurs_connues:
                kwargs[field.name] = valeurs_connues[field.name]
                continue

            if field.has_default() or field.null or field.blank:
                continue

            if field.choices:
                kwargs[field.name] = field.choices[0][0]
            elif isinstance(field, models.CharField):
                kwargs[field.name] = f"TEST-{uuid4().hex[:8]}"
            elif isinstance(field, models.TextField):
                kwargs[field.name] = "Texte de test"
            elif isinstance(field, models.PositiveIntegerField) or isinstance(field, models.IntegerField):
                kwargs[field.name] = 1
            elif isinstance(field, models.DateField):
                kwargs[field.name] = timezone.now().date()
            elif isinstance(field, models.DateTimeField):
                kwargs[field.name] = timezone.now()
            elif isinstance(field, models.BooleanField):
                kwargs[field.name] = False

        return SessionImmersion.objects.create(**kwargs)

    def creer_import_et_ligne(self, type_source, donnees):
        """Crée un ImportOfficiel déjà validé avec une LigneImport valide."""

        session = self.creer_session()

        import_officiel = ImportOfficiel.objects.create(
            session=session,
            type_source=type_source,
            type_fichier=ImportOfficiel.TypeFichier.EXCEL,
            fichier=f"tests/imports/{uuid4().hex}.xlsx",
            nom_fichier_original="liste_test.xlsx",
            taille_fichier=128,
            hash_fichier=uuid4().hex,
            statut=ImportOfficiel.Statut.VALIDE,
            colonnes_detectees=list(donnees.keys()),
            parametres_lecture={
                "type_fichier": "EXCEL",
                "feuille": "Feuil1",
                "ligne_entete": 1,
                "premiere_ligne_donnees": 2,
            },
        )

        ligne = LigneImport.objects.create(
            import_officiel=import_officiel,
            numero_ligne=2,
            donnees_brutes=donnees,
            donnees_normalisees=donnees,
            statut=LigneImport.Statut.VALIDE,
        )

        return import_officiel, ligne

    def confirmer(self, import_officiel):
        """Confirme l'import avec le service qui relie imports_app à immerges."""

        return ImportVersImmergeService.confirmer_import(import_officiel.id)

    def test_confirmer_import_bac_cree_source_examen_et_immerge(self):
        import_officiel, ligne = self.creer_import_et_ligne(
            ImportOfficiel.TypeSource.BAC,
            {
                "numero_pv": "PV-BAC-001",
                "type_examen": "BAC",
                "serie": "D",
                "annee_obtention": 2026,
                "statut": "ADMIS",
                "nom": "KABORE",
                "prenoms": "Ali",
                "sexe": "M",
                "telephone": "70000000",
            },
        )

        resultat = self.confirmer(import_officiel)

        self.assertEqual(resultat["lignes_importees"], 1)
        self.assertEqual(ImmergeExamen.objects.count(), 1)
        self.assertEqual(Immerge.objects.count(), 1)

        source = ImmergeExamen.objects.first()
        immerge = Immerge.objects.first()

        self.assertEqual(source.numero_pv, "PV-BAC-001")
        self.assertEqual(source.type_examen, "BAC")
        self.assertEqual(immerge.type_immerge, Immerge.TypeImmerge.BAC)
        self.assertEqual(immerge.origine_id, source.id)
        self.assertTrue(immerge.code_fasoim.startswith("IP"))
        self.assertTrue(immerge.qr_code.startswith("FASOIM:"))

        ligne.refresh_from_db()
        import_officiel.refresh_from_db()
        self.assertEqual(ligne.statut, LigneImport.Statut.IMPORTEE)
        self.assertEqual(import_officiel.statut, ImportOfficiel.Statut.TERMINE)

    def test_confirmer_import_concours_cree_source_concours_et_immerge(self):
        import_officiel, ligne = self.creer_import_et_ligne(
            ImportOfficiel.TypeSource.CONCOURS,
            {
                "numero_recepisse": "REC-001",
                "nom": "OUEDRAOGO",
                "prenoms": "Awa",
                "sexe": "F",
                "specialite": "Administration",
                "centre_composition": "Ouagadougou",
            },
        )

        self.confirmer(import_officiel)

        self.assertEqual(ImmergeConcours.objects.count(), 1)
        self.assertEqual(Immerge.objects.count(), 1)

        source = ImmergeConcours.objects.first()
        immerge = Immerge.objects.first()

        self.assertEqual(source.numero_recepisse, "REC-001")
        self.assertEqual(source.specialite, "Administration")
        self.assertEqual(immerge.type_immerge, Immerge.TypeImmerge.CONCOURS)
        self.assertEqual(immerge.origine_id, source.id)

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, LigneImport.Statut.IMPORTEE)

    def test_confirmer_import_selectionnes_cree_source_selectionnee_et_immerge(self):
        import_officiel, ligne = self.creer_import_et_ligne(
            ImportOfficiel.TypeSource.SELECTIONNES,
            {
                "matricule": "MAT-001",
                "reference_selection": "REF-2026-001",
                "nom": "SOME",
                "prenoms": "Paul",
                "structure_origine": "Direction régionale",
                "motif_selection": "Liste officielle",
            },
        )

        self.confirmer(import_officiel)

        self.assertEqual(ImmergeSelectionne.objects.count(), 1)
        self.assertEqual(Immerge.objects.count(), 1)

        source = ImmergeSelectionne.objects.first()
        immerge = Immerge.objects.first()

        self.assertEqual(source.matricule, "MAT-001")
        self.assertEqual(source.reference_selection, "REF-2026-001")
        self.assertEqual(immerge.type_immerge, Immerge.TypeImmerge.SELECTIONNE)
        self.assertEqual(immerge.origine_id, source.id)

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, LigneImport.Statut.IMPORTEE)

    def test_confirmer_import_volontaires_acceptes_cree_inscription_et_immerge(self):
        import_officiel, ligne = self.creer_import_et_ligne(
            ImportOfficiel.TypeSource.VOLONTAIRES_ACCEPTES,
            {
                "nom": "TRAORE",
                "prenoms": "Moussa",
                "sexe": "M",
                "telephone": "71000000",
                "region_residence": "Centre",
                "motivation": "Participer à l'immersion patriotique.",
            },
        )

        self.confirmer(import_officiel)

        self.assertEqual(InscriptionVolontaire.objects.count(), 1)
        self.assertEqual(Immerge.objects.count(), 1)

        inscription = InscriptionVolontaire.objects.first()
        immerge = Immerge.objects.first()

        self.assertTrue(inscription.code_suivi)
        self.assertEqual(inscription.statut_demande, InscriptionVolontaire.StatutDemande.ACCEPTEE)
        self.assertEqual(immerge.type_immerge, Immerge.TypeImmerge.VOLONTAIRE)
        self.assertEqual(immerge.origine_id, inscription.id)

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, LigneImport.Statut.IMPORTEE)

    def test_routes_immerges_sont_branchees(self):
        """Vérifie que les routes API du module immerges existent."""

        self.assertEqual(reverse("immerges:immerge-list"), "/api/immerges/immerges/")
        self.assertEqual(reverse("immerges:immerge-examen-list"), "/api/immerges/examens/")
        self.assertEqual(reverse("immerges:inscription-volontaire-list"), "/api/immerges/volontaires/")
