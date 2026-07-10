from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    CorrespondanceColonneImport,
    ErreurImport,
    ImportOfficiel,
    LigneImport,
)


class BaseImportRepository:
    """Méthodes communes aux repositories du module imports.

    Le repository ne lance pas Celery et ne parle pas directement à Redis.
    Il prépare seulement les requêtes optimisées que les services et les tâches
    asynchrones utilisent ensuite.
    """

    @staticmethod
    def identifiant(objet_ou_id):
        return getattr(objet_ou_id, "id", objet_ou_id)

    @staticmethod
    def normaliser_texte(valeur):
        if valeur is None:
            return ""
        return str(valeur).strip()

    @staticmethod
    def appliquer_recherche_import(queryset, recherche):
        recherche = BaseImportRepository.normaliser_texte(recherche)
        if not recherche:
            return queryset

        return queryset.filter(
            Q(nom_fichier_original__icontains=recherche)
            | Q(hash_fichier__icontains=recherche)
            | Q(commentaire__icontains=recherche)
            | Q(message_erreur__icontains=recherche)
        )


class ImportOfficielRepository(BaseImportRepository):
    """Requêtes optimisées liées aux dossiers d'import."""

    @staticmethod
    def queryset():
        return ImportOfficiel.objects.select_related(
            "session",
            "importe_par",
            "correspondance_confirmee_par",
            "confirme_par",
        )

    @staticmethod
    def tous():
        return ImportOfficielRepository.queryset()

    @staticmethod
    def non_supprimes():
        return ImportOfficielRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actifs():
        return ImportOfficielRepository.non_supprimes()

    @staticmethod
    def get_by_id(import_id):
        return ImportOfficielRepository.actifs().filter(id=import_id).first()

    @staticmethod
    def get_any_by_id(import_id):
        return ImportOfficielRepository.queryset().filter(id=import_id).first()

    @staticmethod
    def get_by_id_pour_update(import_id):
        return (
            ImportOfficiel.objects.select_for_update(of=("self",))
            .select_related(
                "session",
                "importe_par",
                "correspondance_confirmee_par",
                "confirme_par",
            )
            .filter(id=import_id, deleted_at__isnull=True)
            .first()
        )

    @staticmethod
    def lister(
        *,
        session_id=None,
        type_source=None,
        statut=None,
        date_debut=None,
        date_fin=None,
        recherche=None,
    ):
        queryset = ImportOfficielRepository.actifs()

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if type_source:
            queryset = queryset.filter(type_source=type_source)
        if statut:
            queryset = queryset.filter(statut=statut)
        if date_debut:
            queryset = queryset.filter(date_import__date__gte=date_debut)
        if date_fin:
            queryset = queryset.filter(date_import__date__lte=date_fin)

        queryset = ImportOfficielRepository.appliquer_recherche_import(queryset, recherche)
        return queryset.order_by("-date_import", "-id")

    @staticmethod
    def lister_par_session(session):
        return ImportOfficielRepository.actifs().filter(
            session_id=ImportOfficielRepository.identifiant(session)
        )

    @staticmethod
    def lister_par_statut(statut):
        return ImportOfficielRepository.actifs().filter(statut=statut)

    @staticmethod
    def lister_par_type_source(type_source):
        return ImportOfficielRepository.actifs().filter(type_source=type_source)

    @staticmethod
    def lister_par_hash(hash_fichier):
        hash_fichier = ImportOfficielRepository.normaliser_texte(hash_fichier)
        if not hash_fichier:
            return ImportOfficielRepository.actifs().none()
        return ImportOfficielRepository.actifs().filter(hash_fichier=hash_fichier)

    @staticmethod
    def lister_en_attente_lecture():
        return ImportOfficielRepository.actifs().filter(statut=ImportOfficiel.Statut.RECU)

    @staticmethod
    def lister_en_attente_correspondance():
        return ImportOfficielRepository.actifs().filter(
            statut=ImportOfficiel.Statut.CORRESPONDANCE_REQUISE
        )

    @staticmethod
    def lister_prets_validation():
        return ImportOfficielRepository.actifs().filter(
            statut=ImportOfficiel.Statut.CORRESPONDANCE_VALIDEE
        )

    @staticmethod
    def lister_prets_confirmation():
        return ImportOfficielRepository.actifs().filter(
            statut__in=[
                ImportOfficiel.Statut.VALIDE,
                ImportOfficiel.Statut.VALIDE_AVEC_ERREURS,
            ]
        )

    @staticmethod
    def compter_par_statut():
        return dict(
            ImportOfficielRepository.actifs()
            .values("statut")
            .annotate(total=Count("id"))
            .values_list("statut", "total")
        )

    @staticmethod
    def mettre_a_jour_statut(import_officiel, statut, message=None):
        import_officiel.statut = statut
        import_officiel.updated_at = timezone.now()
        champs = ["statut", "updated_at"]

        if message is not None:
            import_officiel.message_erreur = message
            champs.append("message_erreur")

        if statut == ImportOfficiel.Statut.LECTURE_COLONNES_EN_COURS:
            import_officiel.date_lecture_colonnes = timezone.now()
            champs.append("date_lecture_colonnes")
        elif statut == ImportOfficiel.Statut.CORRESPONDANCE_VALIDEE:
            import_officiel.date_correspondance = timezone.now()
            champs.append("date_correspondance")
        elif statut == ImportOfficiel.Statut.VALIDATION_EN_COURS:
            import_officiel.date_validation = timezone.now()
            champs.append("date_validation")
        elif statut == ImportOfficiel.Statut.CONFIRMATION_EN_COURS:
            import_officiel.date_confirmation = timezone.now()
            champs.append("date_confirmation")
        elif statut in {
            ImportOfficiel.Statut.TERMINE,
            ImportOfficiel.Statut.ECHEC,
            ImportOfficiel.Statut.ANNULE,
        }:
            import_officiel.date_fin_traitement = timezone.now()
            champs.append("date_fin_traitement")

        import_officiel.save(update_fields=champs)
        return import_officiel

    @staticmethod
    def mettre_a_jour_colonnes_detectees(import_officiel, colonnes, apercu_lignes=None):
        import_officiel.colonnes_detectees = colonnes or []
        import_officiel.date_lecture_colonnes = timezone.now()
        import_officiel.updated_at = timezone.now()
        champs = ["colonnes_detectees", "date_lecture_colonnes", "updated_at"]

        if apercu_lignes is not None:
            import_officiel.apercu_lignes = apercu_lignes or []
            champs.append("apercu_lignes")

        import_officiel.save(update_fields=champs)
        return import_officiel

    @staticmethod
    def mettre_a_jour_statistiques(import_officiel):
        import_id = ImportOfficielRepository.identifiant(import_officiel)
        lignes = LigneImportRepository.lister_par_import(import_id)
        compteur_lignes = dict(
            lignes.values("statut")
            .annotate(total=Count("id"))
            .values_list("statut", "total")
        )

        total_lignes = lignes.count()
        lignes_valides = compteur_lignes.get(LigneImport.Statut.VALIDE, 0)
        lignes_erreur = compteur_lignes.get(LigneImport.Statut.ERREUR, 0)
        lignes_ignorees = compteur_lignes.get(LigneImport.Statut.IGNOREE, 0)
        lignes_importees = compteur_lignes.get(LigneImport.Statut.IMPORTEE, 0)

        ImportOfficiel.objects.filter(id=import_id).update(
            total_lignes=total_lignes,
            lignes_valides=lignes_valides,
            lignes_erreur=lignes_erreur,
            lignes_ignorees=lignes_ignorees,
            lignes_importees=lignes_importees,
            updated_at=timezone.now(),
        )

        if hasattr(import_officiel, "refresh_from_db"):
            import_officiel.refresh_from_db()
        return import_officiel

    @staticmethod
    def soft_delete(import_officiel):
        import_id = ImportOfficielRepository.identifiant(import_officiel)
        return ImportOfficiel.objects.filter(
            id=import_id,
            deleted_at__isnull=True,
        ).update(deleted_at=timezone.now(), updated_at=timezone.now())


class CorrespondanceColonneImportRepository(BaseImportRepository):
    """Requêtes liées aux correspondances entre champs FasoIM et colonnes fichier."""

    @staticmethod
    def queryset():
        return CorrespondanceColonneImport.objects.select_related(
            "import_officiel",
            "import_officiel__session",
        )

    @staticmethod
    def non_supprimees():
        return CorrespondanceColonneImportRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actives():
        return CorrespondanceColonneImportRepository.non_supprimees()

    @staticmethod
    def get_by_id(correspondance_id):
        return CorrespondanceColonneImportRepository.actives().filter(id=correspondance_id).first()

    @staticmethod
    def lister_par_import(import_officiel):
        import_id = CorrespondanceColonneImportRepository.identifiant(import_officiel)
        return CorrespondanceColonneImportRepository.actives().filter(
            import_officiel_id=import_id
        ).order_by("ordre", "champ_cible")

    @staticmethod
    def lister_confirmees_par_import(import_officiel):
        return CorrespondanceColonneImportRepository.lister_par_import(import_officiel).filter(
            confirmee=True
        )

    @staticmethod
    def mapping_par_import(import_officiel, confirmees_seulement=True):
        queryset = CorrespondanceColonneImportRepository.lister_par_import(import_officiel)
        if confirmees_seulement:
            queryset = queryset.filter(confirmee=True)
        return dict(queryset.values_list("champ_cible", "colonne_source"))

    @staticmethod
    def colonnes_sources_par_import(import_officiel, confirmees_seulement=True):
        queryset = CorrespondanceColonneImportRepository.lister_par_import(import_officiel)
        if confirmees_seulement:
            queryset = queryset.filter(confirmee=True)
        return list(queryset.values_list("colonne_source", flat=True))

    @staticmethod
    def existe_champ_cible(import_officiel, champ_cible, exclude_id=None):
        import_id = CorrespondanceColonneImportRepository.identifiant(import_officiel)
        champ_cible = CorrespondanceColonneImportRepository.normaliser_texte(champ_cible)
        queryset = CorrespondanceColonneImportRepository.actives().filter(
            import_officiel_id=import_id,
            champ_cible=champ_cible,
        )
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    @staticmethod
    def existe_colonne_source(import_officiel, colonne_source, exclude_id=None):
        import_id = CorrespondanceColonneImportRepository.identifiant(import_officiel)
        colonne_source = CorrespondanceColonneImportRepository.normaliser_texte(colonne_source)
        queryset = CorrespondanceColonneImportRepository.actives().filter(
            import_officiel_id=import_id,
            colonne_source=colonne_source,
        )
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    @staticmethod
    def creer_en_masse(correspondances, batch_size=500):
        return CorrespondanceColonneImport.objects.bulk_create(
            correspondances,
            batch_size=batch_size,
        )

    @staticmethod
    def mettre_a_jour_en_masse(correspondances, champs, batch_size=500):
        return CorrespondanceColonneImport.objects.bulk_update(
            correspondances,
            champs,
            batch_size=batch_size,
        )

    @staticmethod
    def supprimer_logiquement_par_import(import_officiel):
        import_id = CorrespondanceColonneImportRepository.identifiant(import_officiel)
        return CorrespondanceColonneImportRepository.actives().filter(
            import_officiel_id=import_id
        ).update(deleted_at=timezone.now(), updated_at=timezone.now())


class LigneImportRepository(BaseImportRepository):
    """Requêtes optimisées liées aux lignes importées."""

    @staticmethod
    def queryset():
        return LigneImport.objects.select_related(
            "import_officiel",
            "import_officiel__session",
        )

    @staticmethod
    def non_supprimees():
        return LigneImportRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actives():
        return LigneImportRepository.non_supprimees()

    @staticmethod
    def get_by_id(ligne_id):
        return LigneImportRepository.actives().filter(id=ligne_id).first()

    @staticmethod
    def lister_par_import(import_officiel):
        import_id = LigneImportRepository.identifiant(import_officiel)
        return LigneImportRepository.actives().filter(import_officiel_id=import_id).order_by("numero_ligne")

    @staticmethod
    def lister_par_statut(import_officiel, statut):
        return LigneImportRepository.lister_par_import(import_officiel).filter(statut=statut)

    @staticmethod
    def lister_en_attente(import_officiel):
        return LigneImportRepository.lister_par_statut(import_officiel, LigneImport.Statut.EN_ATTENTE)

    @staticmethod
    def lister_valides(import_officiel):
        return LigneImportRepository.lister_par_statut(import_officiel, LigneImport.Statut.VALIDE)

    @staticmethod
    def lister_erreurs(import_officiel):
        return LigneImportRepository.lister_par_statut(import_officiel, LigneImport.Statut.ERREUR)

    @staticmethod
    def lister_ignorees(import_officiel):
        return LigneImportRepository.lister_par_statut(import_officiel, LigneImport.Statut.IGNOREE)

    @staticmethod
    def lister_importees(import_officiel):
        return LigneImportRepository.lister_par_statut(import_officiel, LigneImport.Statut.IMPORTEE)

    @staticmethod
    def get_par_numero_ligne(import_officiel, numero_ligne):
        return LigneImportRepository.lister_par_import(import_officiel).filter(
            numero_ligne=numero_ligne
        ).first()

    @staticmethod
    def compter_par_statut(import_officiel):
        return dict(
            LigneImportRepository.lister_par_import(import_officiel)
            .values("statut")
            .annotate(total=Count("id"))
            .values_list("statut", "total")
        )

    @staticmethod
    def compter(import_officiel):
        return LigneImportRepository.lister_par_import(import_officiel).count()

    @staticmethod
    def iterator_par_import(import_officiel, chunk_size=1000, statut=None):
        queryset = LigneImportRepository.lister_par_import(import_officiel)
        if statut:
            queryset = queryset.filter(statut=statut)
        return queryset.iterator(chunk_size=chunk_size)

    @staticmethod
    def creer_en_masse(lignes, batch_size=1000):
        return LigneImport.objects.bulk_create(lignes, batch_size=batch_size)

    @staticmethod
    def mettre_a_jour_en_masse(lignes, champs, batch_size=1000):
        return LigneImport.objects.bulk_update(lignes, champs, batch_size=batch_size)

    @staticmethod
    def mettre_a_jour_statut_par_import(import_officiel, statut_source, statut_cible, message=None):
        import_id = LigneImportRepository.identifiant(import_officiel)
        valeurs = {"statut": statut_cible, "updated_at": timezone.now()}
        if message is not None:
            valeurs["message_statut"] = message
        return LigneImportRepository.actives().filter(
            import_officiel_id=import_id,
            statut=statut_source,
        ).update(**valeurs)

    @staticmethod
    def supprimer_logiquement_par_import(import_officiel):
        import_id = LigneImportRepository.identifiant(import_officiel)
        return LigneImportRepository.actives().filter(import_officiel_id=import_id).update(
            deleted_at=timezone.now(),
            updated_at=timezone.now(),
        )


class ErreurImportRepository(BaseImportRepository):
    """Requêtes optimisées liées aux erreurs détectées dans un import."""

    @staticmethod
    def queryset():
        return ErreurImport.objects.select_related(
            "import_officiel",
            "import_officiel__session",
            "ligne_import",
        )

    @staticmethod
    def non_supprimees():
        return ErreurImportRepository.queryset().filter(deleted_at__isnull=True)

    @staticmethod
    def actives():
        return ErreurImportRepository.non_supprimees()

    @staticmethod
    def get_by_id(erreur_id):
        return ErreurImportRepository.actives().filter(id=erreur_id).first()

    @staticmethod
    def lister_par_import(import_officiel):
        import_id = ErreurImportRepository.identifiant(import_officiel)
        return ErreurImportRepository.actives().filter(import_officiel_id=import_id).order_by(
            "ligne_import__numero_ligne",
            "champ_cible",
            "id",
        )

    @staticmethod
    def lister_par_ligne(ligne_import):
        ligne_id = ErreurImportRepository.identifiant(ligne_import)
        return ErreurImportRepository.actives().filter(ligne_import_id=ligne_id).order_by(
            "champ_cible",
            "id",
        )

    @staticmethod
    def filtrer(import_officiel, *, gravite=None, champ_cible=None, type_erreur=None):
        queryset = ErreurImportRepository.lister_par_import(import_officiel)
        if gravite:
            queryset = queryset.filter(gravite=gravite)
        if champ_cible:
            queryset = queryset.filter(champ_cible=champ_cible)
        if type_erreur:
            queryset = queryset.filter(type_erreur=type_erreur)
        return queryset

    @staticmethod
    def lister_bloquantes(import_officiel):
        return ErreurImportRepository.filtrer(
            import_officiel,
            gravite=ErreurImport.Gravite.BLOQUANTE,
        )

    @staticmethod
    def lister_avertissements(import_officiel):
        return ErreurImportRepository.filtrer(
            import_officiel,
            gravite=ErreurImport.Gravite.AVERTISSEMENT,
        )

    @staticmethod
    def compter_par_champ(import_officiel):
        return list(
            ErreurImportRepository.lister_par_import(import_officiel)
            .values("champ_cible")
            .annotate(total=Count("id"))
            .order_by("champ_cible")
        )

    @staticmethod
    def compter_par_type(import_officiel):
        return list(
            ErreurImportRepository.lister_par_import(import_officiel)
            .values("type_erreur")
            .annotate(total=Count("id"))
            .order_by("type_erreur")
        )

    @staticmethod
    def compter_par_gravite(import_officiel):
        return dict(
            ErreurImportRepository.lister_par_import(import_officiel)
            .values("gravite")
            .annotate(total=Count("id"))
            .values_list("gravite", "total")
        )

    @staticmethod
    def creer_en_masse(erreurs, batch_size=1000):
        return ErreurImport.objects.bulk_create(erreurs, batch_size=batch_size)

    @staticmethod
    def supprimer_logiquement_par_import(import_officiel):
        import_id = ErreurImportRepository.identifiant(import_officiel)
        return ErreurImportRepository.actives().filter(import_officiel_id=import_id).update(
            deleted_at=timezone.now(),
            updated_at=timezone.now(),
        )

    @staticmethod
    def supprimer_logiquement_par_ligne(ligne_import):
        ligne_id = ErreurImportRepository.identifiant(ligne_import)
        return ErreurImportRepository.actives().filter(ligne_import_id=ligne_id).update(
            deleted_at=timezone.now(),
            updated_at=timezone.now(),
        )
