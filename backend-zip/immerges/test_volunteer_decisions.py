from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from sessions_app.models import SessionImmersion

from .models import Immerge, InscriptionVolontaire
from .service import InscriptionVolontaireService, ValidationMetierErreur


class InscriptionVolontaireDecisionServiceTests(TestCase):
    def setUp(self):
        aujourd_hui = timezone.localdate()
        self.session = SessionImmersion.objects.create(
            nom="Session volontaires 2026",
            annee=2026,
            numero_promotion=2,
            type_session=SessionImmersion.TypeSession.VOLONTAIRE,
            public_cible=SessionImmersion.PublicCible.VOLONTAIRE,
            date_debut=aujourd_hui + timedelta(days=10),
            date_fin=aujourd_hui + timedelta(days=30),
            date_ouverture_inscription=aujourd_hui - timedelta(days=5),
            date_fermeture_inscription=aujourd_hui + timedelta(days=5),
            statut=SessionImmersion.Statut.OUVERTE,
        )

    def creer_demande(self, statut=InscriptionVolontaire.StatutDemande.EN_ATTENTE):
        motif = "Demande annulée par le volontaire." if statut == InscriptionVolontaire.StatutDemande.ANNULEE else ""
        return InscriptionVolontaire.objects.create(
            session=self.session,
            code_suivi=f"VOL2026{InscriptionVolontaire.objects.count() + 1:06d}",
            nom="OUEDRAOGO",
            prenoms="Awa",
            sexe="F",
            date_naissance=timezone.localdate().replace(year=2002),
            lieu_naissance="Ouagadougou",
            nationalite="Burkinabè",
            numero_cnib=f"B{InscriptionVolontaire.objects.count() + 1:010d}",
            telephone="70000000",
            email=f"volontaire{InscriptionVolontaire.objects.count() + 1}@example.com",
            contact_urgence="71000000",
            nom_contact_urgence="OUEDRAOGO Issa",
            region_residence="Centre",
            province_residence="Kadiogo",
            commune_residence="",
            adresse_residence="Secteur 15, Ouagadougou",
            niveau_etude="",
            profession="Étudiante",
            motivation="Participer à l'immersion patriotique.",
            statut_demande=statut,
            motif_decision=motif,
        )

    def test_demande_annulee_ne_peut_pas_etre_acceptee(self):
        demande = self.creer_demande(InscriptionVolontaire.StatutDemande.ANNULEE)

        with self.assertRaises(ValidationMetierErreur):
            InscriptionVolontaireService.accepter(demande)

        demande.refresh_from_db()
        self.assertEqual(demande.statut_demande, InscriptionVolontaire.StatutDemande.ANNULEE)
        self.assertFalse(Immerge.objects.filter(
            type_immerge=Immerge.TypeImmerge.VOLONTAIRE,
            origine_id=demande.id,
        ).exists())

    def test_demande_annulee_ne_peut_pas_etre_rejetee(self):
        demande = self.creer_demande(InscriptionVolontaire.StatutDemande.ANNULEE)

        with self.assertRaises(ValidationMetierErreur):
            InscriptionVolontaireService.rejeter(
                demande,
                motif_decision="Dossier non retenu.",
            )

        demande.refresh_from_db()
        self.assertEqual(demande.statut_demande, InscriptionVolontaire.StatutDemande.ANNULEE)

    def test_demande_deja_acceptee_ne_peut_pas_etre_retraitee(self):
        demande = self.creer_demande()
        InscriptionVolontaireService.accepter(demande, creer_immerge=False)

        with self.assertRaises(ValidationMetierErreur):
            InscriptionVolontaireService.accepter(demande, creer_immerge=False)

        with self.assertRaises(ValidationMetierErreur):
            InscriptionVolontaireService.rejeter(
                demande,
                motif_decision="Dossier non retenu.",
            )

    def test_rejet_exige_un_motif(self):
        demande = self.creer_demande()

        with self.assertRaises(ValidationMetierErreur):
            InscriptionVolontaireService.rejeter(demande, motif_decision="  ")

        demande.refresh_from_db()
        self.assertEqual(demande.statut_demande, InscriptionVolontaire.StatutDemande.EN_ATTENTE)
