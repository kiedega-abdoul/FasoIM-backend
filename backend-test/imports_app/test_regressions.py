from django.test import SimpleTestCase

from .models import ImportOfficiel
from .service import ValidationImportService
from .views import ImportLargeListPagination


class ImportDateRegressionTests(SimpleTestCase):
    def test_date_excel_iso_avec_heure_est_normalisee(self):
        donnees = {
            "numero_pv": "BAC-001",
            "nom": "OUEDRAOGO",
            "prenoms": "Awa",
            "date_naissance": "2005-01-14T00:00:00",
        }

        erreurs = ValidationImportService._valider_donnees(
            ImportOfficiel.TypeSource.BAC,
            donnees,
        )

        self.assertFalse(
            any(erreur["champ_cible"] == "date_naissance" for erreur in erreurs)
        )
        self.assertEqual(donnees["date_naissance"], "2005-01-14")

    def test_formats_de_date_humains_sont_acceptes(self):
        self.assertEqual(
            ValidationImportService._convertir_date("14/01/2005").isoformat(),
            "2005-01-14",
        )
        self.assertEqual(
            ValidationImportService._convertir_date("14-01-2005").isoformat(),
            "2005-01-14",
        )

