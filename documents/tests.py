from __future__ import annotations

import tempfile
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Acteur, Permission, RolePermission
from activites.models import Evaluation, ModuleActivite, Note, Presence, Seance
from affectations.models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)
from imports_app.models import ImportOfficiel
from immerges.models import Immerge, ImmergeSelectionne
from organisation.models import (
    AffectationGroupe,
    AttributionLit,
    Dortoir,
    Groupe,
    Lit,
    RegleOrganisationCentre,
    Section,
)
from sessions_app.models import ParametreSession, SessionImmersion
from sessions_app.service import SessionImmersionService

from .models import DocumentGenere, PublicationOfficielle, ResultatFinal
from .service import (
    AttestationPubliqueService,
    AttestationService,
    CentreCertificationService,
    EligibiliteAttestationService,
    GenerationFichierService,
    IdentiteImmergeService,
    InformationsArriveeService,
    PublicationService,
    RapportService,
    SessionClotureService,
    ValidationDocumentsErreur,
)


CACHE_TEST = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "documents-tests",
    }
}


@override_settings(
    CACHES=CACHE_TEST,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CELERY_TASK_ALWAYS_EAGER=True,
    FASOIM_PUBLIC_URL="https://fasoim.test",
)
class DocumentsTests(TestCase):
    mot_de_passe = "Documents-2026!"

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.TemporaryDirectory()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media.name)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        cls._media.cleanup()

    def setUp(self):
        cache.clear()
        self.acteur = Acteur.objects.create_superuser(
            username="admin-documents",
            email="admin-documents@fasoim.test",
            password=self.mot_de_passe,
            first_name="Aminata",
            last_name="Ouédraogo",
            titre="Directrice régionale",
            organisation="FasoIM",
            statut=Acteur.Statut.ACTIF,
            is_active=True,
        )
        # Image PNG valide utilisée comme signature et cachet de test.
        png = GenerationFichierService.qr_bytes("signature-test")
        self.acteur.signature_image.save("signature.png", ContentFile(png), save=False)
        self.acteur.cachet_image.save("cachet.png", ContentFile(png), save=False)
        self.acteur.save()

        self.session = SessionImmersion.objects.create(
            nom="Session documents 2026",
            annee=2026,
            numero_promotion=1,
            type_session=SessionImmersion.TypeSession.MIXTE,
            public_cible=SessionImmersion.PublicCible.MIXTE,
            date_debut=date.today() - timedelta(days=20),
            date_fin=date.today() - timedelta(days=1),
            statut=SessionImmersion.Statut.EN_COURS,
        )
        self.parametres = ParametreSession.objects.create(
            session=self.session,
            hebergement_active=False,
            repas_active=False,
            visite_medicale_active=False,
            activites_active=False,
            evaluation_active=False,
            attestation_active=True,
            consultation_publique_active=True,
            taux_presence_minimum_attestation=Decimal("80.00"),
            moyenne_minimum_attestation=Decimal("10.00"),
            directives_generales="Respecter les horaires.",
            consignes_generales="Se présenter avec les pièces demandées.",
            documents_exiges=["CNIB", "Convocation"],
        )
        self.region = RegionImmersion.objects.create(code="DOC-REG", nom="Région documents")
        self.centre = CentreImmersion.objects.create(
            region=self.region,
            code="DOC-CTR",
            nom="Centre documents",
            province="Kadiogo",
            ville="Ouagadougou",
            adresse="Secteur 12",
            genre=CentreImmersion.Genre.MIXTE,
            publics_acceptes=[],
            niveaux_acceptes=[],
        )
        self.import_officiel = ImportOfficiel.objects.create(
            session=self.session,
            type_source=ImportOfficiel.TypeSource.SELECTIONNES,
            type_fichier=ImportOfficiel.TypeFichier.CSV,
            fichier="imports/documents.csv",
            nom_fichier_original="documents.csv",
            statut=ImportOfficiel.Statut.TERMINE,
        )
        self.source = ImmergeSelectionne.objects.create(
            import_officiel=self.import_officiel,
            numero_ligne_import=1,
            matricule="MAT-DOC-001",
            nom="Kaboré",
            prenoms="Awa",
            nom_et_prenoms="Kaboré Awa",
            date_naissance=date(2005, 1, 2),
            email="awa@fasoim.test",
            statut_validation=ImmergeSelectionne.StatutValidation.VALIDE,
        )
        self.immerge = Immerge.objects.create(
            session=self.session,
            type_immerge=Immerge.TypeImmerge.SELECTIONNE,
            origine_id=self.source.id,
            code_fasoim="IP2026SEL0100001",
            qr_code="QR-DOC-001",
            statut=Immerge.Statut.LIBERE,
        )
        self.affectation_regionale = AffectationRegionale.objects.create(
            immerge=self.immerge,
            session=self.session,
            region=self.region,
            statut=AffectationRegionale.Statut.ACTIVE,
            affecte_par=self.acteur,
        )
        self.affectation = AffectationCentre.objects.create(
            immerge=self.immerge,
            session=self.session,
            affectation_regionale=self.affectation_regionale,
            centre=self.centre,
            statut=AffectationCentre.Statut.ACTIVE,
            affecte_par=self.acteur,
        )
        self.regle = RegleOrganisationCentre.objects.create(
            session=self.session,
            centre=self.centre,
            capacite_ouverte=100,
            seuil_division_sections=2,
            capacite_max_section=100,
            seuil_division_groupes=2,
            capacite_max_groupe=50,
            lieu_accueil="Cour principale",
            heure_accueil=time(7, 30),
            horaires_generaux="07h30 à 17h00",
            consignes_accueil="Présenter son code FasoIM.",
            statut=RegleOrganisationCentre.Statut.PRETE_PUBLICATION,
            validee_par=self.acteur,
            date_validation=timezone.now(),
            date_pret_publication=timezone.now(),
        )
        self.section = Section.objects.create(
            session=self.session,
            centre=self.centre,
            nom="Section A",
            code="DOC-SEC-A",
            capacite_max=100,
        )
        self.groupe = Groupe.objects.create(
            section=self.section,
            nom="Groupe A1",
            code="DOC-GRP-A1",
            capacite_max=50,
        )
        AffectationGroupe.objects.create(
            affectation_centre=self.affectation,
            groupe=self.groupe,
            statut=AffectationGroupe.Statut.ACTIVE,
            affecte_par=self.acteur,
        )

    def publier_arrivee(self):
        with patch.object(NotificationServiceProxy, "noop", return_value=None):
            publication = PublicationService.soumettre_arrivee_centre(
                session_id=self.session.id,
                centre_id=self.centre.id,
                acteur=self.acteur,
            )
            PublicationService.valider_region(
                publication_id=publication.id,
                acteur=self.acteur,
            )
            PublicationService.publier_session(
                session_id=self.session.id,
                type_publication=PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE,
                acteur=self.acteur,
            )
        publication.refresh_from_db()
        return publication

    def preparer_activites(self, *, note=Decimal("12.00"), evaluation_statut=Evaluation.Statut.CLOTUREE):
        self.parametres.activites_active = True
        self.parametres.evaluation_active = True
        self.parametres.save(update_fields=["activites_active", "evaluation_active", "updated_at"])
        module = ModuleActivite.objects.create(
            titre="Civisme",
            code=f"DOC-CIV-{self.session.id}",
            categorie=ModuleActivite.Categorie.CIVISME,
            duree_prevue=90,
        )
        seance = Seance.objects.create(
            module_activite=module,
            type_seance=Seance.TypeSeance.EVALUATION,
            session=self.session,
            centre=self.centre,
            groupe=self.groupe,
            date_seance=self.session.date_fin,
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            lieu="Salle A",
            statut=Seance.Statut.TERMINEE,
            statut_feuille_presence=Seance.StatutFeuillePresence.CLOTUREE,
            date_ouverture_presence=timezone.now() - timedelta(minutes=2),
            date_validation_presence=timezone.now() - timedelta(minutes=1),
            date_cloture_presence=timezone.now(),
        )
        Presence.objects.create(
            seance=seance,
            affectation_centre=self.affectation,
            statut_presence=Presence.StatutPresence.PRESENT,
            saisie_par=self.acteur,
        )
        evaluation = Evaluation.objects.create(
            session=self.session,
            centre=self.centre,
            seance=seance,
            titre="Évaluation finale",
            type_evaluation=Evaluation.TypeEvaluation.FINALE,
            bareme=Decimal("20.00"),
            coefficient=Decimal("1.00"),
            date_evaluation=timezone.now(),
            statut=evaluation_statut,
            created_by=self.acteur,
        )
        if evaluation_statut == Evaluation.Statut.CLOTUREE:
            Note.objects.create(
                evaluation=evaluation,
                affectation_centre=self.affectation,
                valeur=note,
                statut_note=Note.StatutNote.NOTEE,
                saisie_par=self.acteur,
            )
        return seance, evaluation

    def cycle_attestation_jusqua_publication(self):
        self.publier_arrivee()
        EligibiliteAttestationService.calculer_centre(
            session_id=self.session.id,
            centre_id=self.centre.id,
            acteur=self.acteur,
        )
        EligibiliteAttestationService.valider_centre(
            session_id=self.session.id,
            centre_id=self.centre.id,
            acteur=self.acteur,
        )
        AttestationService.generer_centre(
            session_id=self.session.id,
            centre_id=self.centre.id,
            acteur=self.acteur,
        )
        publication = PublicationService.soumettre_attestations_centre(
            session_id=self.session.id,
            centre_id=self.centre.id,
            acteur=self.acteur,
        )
        AttestationService.signer_region(
            publication_id=publication.id,
            acteur=self.acteur,
        )
        PublicationService.publier_session(
            session_id=self.session.id,
            type_publication=PublicationOfficielle.TypePublication.ATTESTATIONS,
            acteur=self.acteur,
        )
        return DocumentGenere.objects.get(type_document=DocumentGenere.TypeDocument.ATTESTATION)

    def test_identite_est_resolue_depuis_la_table_source(self):
        identite = IdentiteImmergeService.donnees(self.immerge)
        self.assertEqual(identite["nom_complet"], "Kaboré Awa")
        self.assertEqual(identite["identifiant_origine"], "MAT-DOC-001")

    def test_arrivee_non_consultable_avant_publication(self):
        with self.assertRaises(ValidationDocumentsErreur):
            InformationsArriveeService.construire(self.immerge, journaliser=False)

    def test_cycle_publication_arrivee_et_consultation(self):
        self.publier_arrivee()
        donnees = InformationsArriveeService.construire(self.immerge, journaliser=False)
        self.assertEqual(donnees["affectation"]["centre"], self.centre.nom)
        self.assertEqual(donnees["affectation"]["section"], self.section.nom)
        self.assertEqual(donnees["affectation"]["groupe"], self.groupe.nom)
        self.assertIsNone(donnees["hebergement"])

    def test_recherche_publique_par_matricule(self):
        resultat = IdentiteImmergeService.rechercher_public(
            type_immerge=Immerge.TypeImmerge.SELECTIONNE,
            identifiant="MAT-DOC-001",
            session_code=self.session.code,
            date_naissance=date(2005, 1, 2),
        )
        self.assertEqual(resultat.id, self.immerge.id)

    def test_valider_region_refuse_un_lot_attestations_non_signe(self):
        resultat = ResultatFinal.objects.create(
            session=self.session,
            region=self.region,
            centre=self.centre,
            affectation_centre=self.affectation,
            immerge=self.immerge,
            decision=ResultatFinal.Decision.NON_ELIGIBLE,
            statut=ResultatFinal.Statut.VALIDE_CENTRE,
        )
        publication = PublicationService.soumettre_attestations_centre(
            session_id=self.session.id,
            centre_id=self.centre.id,
            acteur=self.acteur,
        )
        with self.assertRaises(ValidationDocumentsErreur):
            PublicationService.valider_region(
                publication_id=publication.id,
                acteur=self.acteur,
            )
        resultat.refresh_from_db()
        self.assertEqual(resultat.statut, ResultatFinal.Statut.SOUMIS_REGION)

    def test_eligibilite_sans_modules_facultatifs(self):
        donnees = EligibiliteAttestationService.calculer(
            affectation=self.affectation,
            acteur=self.acteur,
        )
        self.assertEqual(donnees["decision"], ResultatFinal.Decision.ELIGIBLE)
        self.assertIsNone(donnees["moyenne_sur_20"])

    def test_moyenne_au_moins_dix_est_eligible(self):
        self.preparer_activites(note=Decimal("12.00"))
        donnees = EligibiliteAttestationService.calculer(
            affectation=self.affectation,
            acteur=self.acteur,
        )
        self.assertEqual(donnees["decision"], ResultatFinal.Decision.ELIGIBLE)
        self.assertEqual(donnees["moyenne_sur_20"], Decimal("12.00"))

    def test_moyenne_inferieure_a_dix_est_non_eligible(self):
        self.preparer_activites(note=Decimal("8.00"))
        donnees = EligibiliteAttestationService.calculer(
            affectation=self.affectation,
            acteur=self.acteur,
        )
        self.assertEqual(donnees["decision"], ResultatFinal.Decision.NON_ELIGIBLE)
        self.assertIn("MOYENNE_INSUFFISANTE", donnees["motifs"])

    def test_evaluation_non_cloturee_reste_a_verifier(self):
        self.preparer_activites(evaluation_statut=Evaluation.Statut.OUVERTE)
        donnees = EligibiliteAttestationService.calculer(
            affectation=self.affectation,
            acteur=self.acteur,
        )
        self.assertEqual(donnees["decision"], ResultatFinal.Decision.A_VERIFIER)
        self.assertIn("EVALUATIONS_NON_CLOTUREES", donnees["motifs"])

    def test_immerge_non_libere_reste_a_verifier(self):
        self.immerge.statut = Immerge.Statut.EN_IMMERSION
        self.immerge.save(update_fields=["statut", "updated_at"])
        donnees = EligibiliteAttestationService.calculer(
            affectation=self.affectation,
            acteur=self.acteur,
        )
        self.assertEqual(donnees["decision"], ResultatFinal.Decision.A_VERIFIER)
        self.assertIn("IMMERSION_NON_LIBEREE", donnees["motifs"])

    def test_generation_attestation_est_idempotente(self):
        self.publier_arrivee()
        EligibiliteAttestationService.calculer_centre(
            session_id=self.session.id, centre_id=self.centre.id, acteur=self.acteur
        )
        EligibiliteAttestationService.valider_centre(
            session_id=self.session.id, centre_id=self.centre.id, acteur=self.acteur
        )
        premier = AttestationService.generer_centre(
            session_id=self.session.id, centre_id=self.centre.id, acteur=self.acteur
        )
        second = AttestationService.generer_centre(
            session_id=self.session.id, centre_id=self.centre.id, acteur=self.acteur
        )
        self.assertEqual(premier["generes"], 1)
        self.assertEqual(second["deja_generes"], 1)
        self.assertEqual(DocumentGenere.objects.filter(type_document=DocumentGenere.TypeDocument.ATTESTATION).count(), 1)

    def test_soumission_attestations_libere_les_lits_du_centre(self):
        self.parametres.hebergement_active = True
        self.parametres.save(
            update_fields=["hebergement_active", "updated_at"]
        )
        dortoir = Dortoir.objects.create(
            centre=self.centre,
            nom="Dortoir test",
            capacite=1,
            sexe_dortoir=Dortoir.SexeDortoir.FEMININ,
        )
        lit = Lit.objects.create(
            dortoir=dortoir,
            numero_lit="01",
        )
        attribution = AttributionLit.objects.create(
            affectation_centre=self.affectation,
            lit=lit,
            statut=AttributionLit.Statut.ACTIVE,
            attribue_par=self.acteur,
        )
        ResultatFinal.objects.create(
            session=self.session,
            region=self.region,
            centre=self.centre,
            affectation_centre=self.affectation,
            immerge=self.immerge,
            decision=ResultatFinal.Decision.NON_ELIGIBLE,
            statut=ResultatFinal.Statut.VALIDE_CENTRE,
        )

        publication = PublicationService.soumettre_attestations_centre(
            session_id=self.session.id,
            centre_id=self.centre.id,
            acteur=self.acteur,
        )

        attribution.refresh_from_db()
        self.assertEqual(
            attribution.statut,
            AttributionLit.Statut.LIBEREE,
        )
        self.assertIsNotNone(attribution.date_liberation)
        self.assertIsNotNone(attribution.deleted_at)
        self.assertEqual(
            publication.resume["hebergement"]["lits_liberes"],
            1,
        )
        self.assertFalse(
            AttributionLit.objects.filter(
                lit=lit,
                statut__in=[
                    AttributionLit.Statut.PROPOSEE,
                    AttributionLit.Statut.ACTIVE,
                    AttributionLit.Statut.A_REORGANISER,
                ],
                deleted_at__isnull=True,
            ).exists()
        )

    def test_finalisation_signale_les_lits_a_reorganiser(self):
        self.parametres.hebergement_active = True
        self.parametres.save(
            update_fields=["hebergement_active", "updated_at"]
        )
        dortoir = Dortoir.objects.create(
            centre=self.centre,
            nom="Dortoir à revoir",
            capacite=1,
            sexe_dortoir=Dortoir.SexeDortoir.FEMININ,
        )
        lit = Lit.objects.create(
            dortoir=dortoir,
            numero_lit="01",
        )
        AttributionLit.objects.create(
            affectation_centre=self.affectation,
            lit=lit,
            statut=AttributionLit.Statut.A_REORGANISER,
            attribue_par=self.acteur,
        )

        etat = CentreCertificationService.verifier(
            session=self.session,
            centre=self.centre,
        )

        codes = {blocage["code"] for blocage in etat["blocages"]}
        self.assertIn("LITS_A_REORGANISER", codes)

    def test_cycle_complet_attestation_signature_publication_verification(self):
        document = self.cycle_attestation_jusqua_publication()
        document.refresh_from_db()
        self.assertEqual(document.statut, DocumentGenere.Statut.PUBLIE)
        self.assertTrue(document.signature_appliquee)
        self.assertTrue(document.cachet_applique)
        self.assertTrue(document.hash_sha256)
        verification = AttestationPubliqueService.verifier(
            code=document.code_verification,
            journaliser=False,
        )
        self.assertTrue(verification["valide"])

    def test_consultation_publique_attestation(self):
        document = self.cycle_attestation_jusqua_publication()
        donnees = AttestationPubliqueService.consulter_immerge(
            immerge=self.immerge,
            request=None,
        )
        self.assertTrue(donnees["attestation_disponible"])
        self.assertEqual(donnees["numero_document"], document.numero_document)

    def test_integrite_detecte_un_fichier_modifie(self):
        document = self.cycle_attestation_jusqua_publication()
        with open(document.fichier.path, "wb") as fichier:
            fichier.write(b"fichier modifie")
        verification = AttestationPubliqueService.verifier(
            code=document.code_verification,
            journaliser=False,
        )
        self.assertFalse(verification["valide"])
        self.assertFalse(verification["integrite"])

    def test_rapport_pdf_xlsx_csv(self):
        for format_fichier in (
            DocumentGenere.Format.PDF,
            DocumentGenere.Format.XLSX,
            DocumentGenere.Format.CSV,
        ):
            document = RapportService.generer(
                type_document=DocumentGenere.TypeDocument.LISTE_IMMERGES,
                format_fichier=format_fichier,
                session_id=self.session.id,
                centre_id=self.centre.id,
                acteur=self.acteur,
            )
            self.assertEqual(document.statut, DocumentGenere.Statut.GENERE)
            self.assertTrue(document.fichier)
            self.assertGreater(document.taille_octets, 0)

    def test_un_rapport_en_echec_ne_bloque_pas_la_cloture(self):
        DocumentGenere.objects.create(
            type_document=DocumentGenere.TypeDocument.RAPPORT_CENTRE,
            format_fichier=DocumentGenere.Format.PDF,
            titre="Rapport en échec",
            session=self.session,
            centre=self.centre,
            statut=DocumentGenere.Statut.ECHEC,
            message_erreur="Erreur simulée",
        )
        codes = {b["code"] for b in SessionClotureService.verifier(self.session).blocages}
        self.assertNotIn("RAPPORT_EN_ECHEC", codes)

    def test_cloture_refusee_avant_publication_des_documents_obligatoires(self):
        etat = SessionClotureService.verifier(self.session)
        self.assertFalse(etat.cloturable)
        codes = {blocage["code"] for blocage in etat.blocages}
        self.assertIn("INFORMATIONS_ARRIVEE_NON_PUBLIEES", codes)
        self.assertIn("RESULTATS_FINAUX_INCOMPLETS", codes)

    def test_cloture_autorisee_apres_cycle_complet(self):
        self.cycle_attestation_jusqua_publication()
        etat = SessionClotureService.verifier(self.session)
        self.assertTrue(etat.cloturable, etat.blocages)
        SessionImmersionService.terminer_session(self.session)
        self.session.refresh_from_db()
        self.assertEqual(self.session.statut, SessionImmersion.Statut.TERMINEE)

    def test_aucune_operation_documentaire_apres_session_terminee(self):
        self.cycle_attestation_jusqua_publication()
        SessionImmersionService.terminer_session(self.session)
        with self.assertRaises(ValidationDocumentsErreur):
            RapportService.generer(
                type_document=DocumentGenere.TypeDocument.LISTE_IMMERGES,
                format_fichier=DocumentGenere.Format.PDF,
                session_id=self.session.id,
                centre_id=self.centre.id,
                acteur=self.acteur,
            )

    def test_api_publique_arrivee_et_verification(self):
        self.publier_arrivee()
        client = APIClient()
        response = client.post(
            "/api/documents/public/arrivee/",
            {"code_fasoim": self.immerge.code_fasoim},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["affectation"]["centre"], self.centre.nom)

    def test_seed_documents(self):
        call_command("seed_accounts", verbosity=0)
        self.assertEqual(
            Permission.objects.filter(
                module="documents",
                statut=Permission.Statut.ACTIVE,
                deleted_at__isnull=True,
            ).count(),
            15,
        )
        self.assertEqual(
            RolePermission.objects.filter(
                permission__module="documents",
                deleted_at__isnull=True,
            ).count(),
            52,
        )


class NotificationServiceProxy:
    """Simple cible de patch locale ; les callbacks réels sont différés par transaction.on_commit."""

    @staticmethod
    def noop():
        return None
