from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from imports_app.models import CorrespondanceColonneImport, ErreurImport, ImportOfficiel, LigneImport

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "IMP_TRAITEMENT_BLOQUE",
    "IMP_ECHEC",
    "IMP_CORRESPONDANCE_INCOMPLETE",
    "IMP_COMPTEURS_INCOHERENTS",
    "IMP_LIGNES_ORPHELINES",
    "IMP_ERREURS_BLOQUANTES_APRES_VALIDATION",
    "IMP_DOUBLON_HASH",
)


def _taille_lot():
    return int(getattr(settings, "INCIDENTS_TAILLE_LOT_SCAN", getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500)))


def detecter():
    maintenant = timezone.now()
    taille_lot = _taille_lot()
    statuts_traitement = [
        ImportOfficiel.Statut.LECTURE_COLONNES_EN_COURS,
        ImportOfficiel.Statut.VALIDATION_EN_COURS,
        ImportOfficiel.Statut.CONFIRMATION_EN_COURS,
    ]
    bloques = ImportOfficiel.objects.filter(
        statut__in=statuts_traitement,
        updated_at__lt=maintenant - timedelta(minutes=30),
        deleted_at__isnull=True,
    ).select_related("session").iterator(chunk_size=taille_lot)
    for dossier in bloques:
        yield Anomalie(
            code="IMP_TRAITEMENT_BLOQUE",
            cle=f"IMP_TRAITEMENT_BLOQUE:{dossier.id}",
            titre="Traitement d'import bloqué",
            description=(
                f"L'import {dossier.nom_fichier_original} reste au statut {dossier.statut} "
                "depuis plus de trente minutes."
            ),
            categorie=AlerteIncident.Categorie.IMPORT,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.DONNEE,
            session_id=dossier.session_id,
            module_source="imports_app",
            modele_source="ImportOfficiel",
            objet_source_id=dossier.id,
            est_bloquante=True,
        )

    for dossier in ImportOfficiel.objects.filter(
        statut=ImportOfficiel.Statut.ECHEC,
        deleted_at__isnull=True,
    ).select_related("session").iterator(chunk_size=taille_lot):
        yield Anomalie(
            code="IMP_ECHEC",
            cle=f"IMP_ECHEC:{dossier.id}",
            titre="Échec d'un import officiel",
            description=(
                "Un import officiel est en échec. Le détail technique reste dans le dossier "
                "d'import et n'est pas recopié dans l'alerte."
            ),
            categorie=AlerteIncident.Categorie.IMPORT,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.DONNEE,
            session_id=dossier.session_id,
            module_source="imports_app",
            modele_source="ImportOfficiel",
            objet_source_id=dossier.id,
            est_bloquante=True,
            contexte={"nom_fichier": dossier.nom_fichier_original},
        )

    imports_mapping = (
        ImportOfficiel.objects.filter(
            statut__in=[
                ImportOfficiel.Statut.CORRESPONDANCE_VALIDEE,
                ImportOfficiel.Statut.VALIDATION_EN_COURS,
                ImportOfficiel.Statut.VALIDE,
                ImportOfficiel.Statut.VALIDE_AVEC_ERREURS,
                ImportOfficiel.Statut.CONFIRMATION_EN_COURS,
                ImportOfficiel.Statut.TERMINE,
            ],
            deleted_at__isnull=True,
        )
        .annotate(
            correspondances_incompletes_calculees=Count(
                "correspondances",
                filter=Q(
                    correspondances__obligatoire=True,
                    correspondances__confirmee=False,
                    correspondances__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
            total_lignes_calcule=Count(
                "lignes",
                filter=Q(lignes__deleted_at__isnull=True),
                distinct=True,
            ),
            lignes_valides_calculees=Count(
                "lignes",
                filter=Q(
                    lignes__statut=LigneImport.Statut.VALIDE,
                    lignes__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
            lignes_erreur_calculees=Count(
                "lignes",
                filter=Q(
                    lignes__statut=LigneImport.Statut.ERREUR,
                    lignes__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
            lignes_ignorees_calculees=Count(
                "lignes",
                filter=Q(
                    lignes__statut=LigneImport.Statut.IGNOREE,
                    lignes__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
            lignes_importees_calculees=Count(
                "lignes",
                filter=Q(
                    lignes__statut=LigneImport.Statut.IMPORTEE,
                    lignes__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
            erreurs_bloquantes_calculees=Count(
                "erreurs",
                filter=Q(
                    erreurs__gravite=ErreurImport.Gravite.BLOQUANTE,
                    erreurs__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
        )
        .iterator(chunk_size=taille_lot)
    )
    for dossier in imports_mapping:
        incompletes = dossier.correspondances_incompletes_calculees
        if incompletes:
            yield Anomalie(
                code="IMP_CORRESPONDANCE_INCOMPLETE",
                cle=f"IMP_CORRESPONDANCE_INCOMPLETE:{dossier.id}",
                titre="Correspondance obligatoire non confirmée",
                description=(
                    f"{incompletes} correspondance(s) obligatoire(s) ne sont pas confirmées "
                    "alors que l'import a dépassé l'étape de correspondance."
                ),
                categorie=AlerteIncident.Categorie.IMPORT,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.DONNEE,
                session_id=dossier.session_id,
                module_source="imports_app",
                modele_source="ImportOfficiel",
                objet_source_id=dossier.id,
                est_bloquante=True,
                contexte={"correspondances_incompletes": incompletes},
            )

        total_calcule = dossier.total_lignes_calcule
        repartition = {
            LigneImport.Statut.VALIDE: dossier.lignes_valides_calculees,
            LigneImport.Statut.ERREUR: dossier.lignes_erreur_calculees,
            LigneImport.Statut.IGNOREE: dossier.lignes_ignorees_calculees,
            LigneImport.Statut.IMPORTEE: dossier.lignes_importees_calculees,
        }
        incoherent = (
            dossier.total_lignes != total_calcule
            or dossier.lignes_valides != repartition.get(LigneImport.Statut.VALIDE, 0)
            or dossier.lignes_erreur != repartition.get(LigneImport.Statut.ERREUR, 0)
            or dossier.lignes_ignorees != repartition.get(LigneImport.Statut.IGNOREE, 0)
            or dossier.lignes_importees != repartition.get(LigneImport.Statut.IMPORTEE, 0)
        )
        if incoherent:
            yield Anomalie(
                code="IMP_COMPTEURS_INCOHERENTS",
                cle=f"IMP_COMPTEURS_INCOHERENTS:{dossier.id}",
                titre="Compteurs d'import incohérents",
                description="Les compteurs enregistrés sur l'import ne correspondent pas aux lignes persistées.",
                categorie=AlerteIncident.Categorie.IMPORT,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.DONNEE,
                session_id=dossier.session_id,
                module_source="imports_app",
                modele_source="ImportOfficiel",
                objet_source_id=dossier.id,
                contexte={
                    "total_enregistre": dossier.total_lignes,
                    "total_calcule": total_calcule,
                    "repartition_calculee": repartition,
                },
            )

        bloquantes = dossier.erreurs_bloquantes_calculees
        if bloquantes and dossier.statut in {
            ImportOfficiel.Statut.VALIDE,
            ImportOfficiel.Statut.CONFIRMATION_EN_COURS,
            ImportOfficiel.Statut.TERMINE,
        }:
            yield Anomalie(
                code="IMP_ERREURS_BLOQUANTES_APRES_VALIDATION",
                cle=f"IMP_ERREURS_BLOQUANTES_APRES_VALIDATION:{dossier.id}",
                titre="Import validé avec erreurs bloquantes",
                description=(
                    f"L'import est au statut {dossier.statut} alors que {bloquantes} erreur(s) "
                    "bloquante(s) sont encore actives."
                ),
                categorie=AlerteIncident.Categorie.IMPORT,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.DONNEE,
                session_id=dossier.session_id,
                module_source="imports_app",
                modele_source="ImportOfficiel",
                objet_source_id=dossier.id,
                est_bloquante=True,
                contexte={"erreurs_bloquantes": bloquantes},
            )

    # La cohérence import/ligne est déjà protégée par le modèle. Le contrôle utile
    # porte ici sur les lignes actives d'un import supprimé logiquement.
    for ligne in (
        LigneImport.objects.filter(
            deleted_at__isnull=True,
            import_officiel__deleted_at__isnull=False,
        )
        .select_related("import_officiel")
        .iterator(chunk_size=taille_lot)
    ):
        yield Anomalie(
            code="IMP_LIGNES_ORPHELINES",
            cle=f"IMP_LIGNES_ORPHELINES:{ligne.id}",
            titre="Ligne active rattachée à un import supprimé",
            description="Une ligne d'import reste active alors que son dossier parent est supprimé logiquement.",
            categorie=AlerteIncident.Categorie.IMPORT,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.DONNEE,
            session_id=ligne.import_officiel.session_id,
            module_source="imports_app",
            modele_source="LigneImport",
            objet_source_id=ligne.id,
        )

    doublons = (
        ImportOfficiel.objects.filter(
            deleted_at__isnull=True,
        )
        .exclude(hash_fichier="")
        .values("session_id", "hash_fichier")
        .annotate(total=Count("id"))
        .filter(total__gt=1).iterator(chunk_size=taille_lot)
    )
    for ligne in doublons:
        yield Anomalie(
            code="IMP_DOUBLON_HASH",
            cle=f"IMP_DOUBLON_HASH:{ligne['session_id']}:{ligne['hash_fichier']}",
            titre="Fichier importé plusieurs fois",
            description="Plusieurs imports actifs de la même session possèdent le même hash de fichier.",
            categorie=AlerteIncident.Categorie.IMPORT,
            gravite=AlerteIncident.NiveauGravite.MOYEN,
            type_concerne=AlerteIncident.TypeConcerne.SESSION,
            session_id=ligne["session_id"],
            module_source="imports_app",
            modele_source="ImportOfficiel",
            contexte={"nombre_imports": ligne["total"]},
        )
