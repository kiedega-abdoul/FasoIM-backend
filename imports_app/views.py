from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import CorrespondanceColonneImport, ErreurImport, ImportOfficiel, LigneImport
from .permissions import (
    PermissionCorrespondanceColonneImport,
    PermissionErreurImport,
    PermissionImportOfficiel,
    PermissionLigneImport,
)
from .repository import (
    CorrespondanceColonneImportRepository,
    ErreurImportRepository,
    ImportOfficielRepository,
    LigneImportRepository,
)
from .serializers import (
    AnnulerImportSerializer,
    ChampsAttendusTypeSourceSerializer,
    CorrespondanceColonneImportSerializer,
    ErreurImportSerializer,
    ImportOfficielCreateSerializer,
    ImportOfficielDetailSerializer,
    ImportOfficielListSerializer,
    LigneImportSerializer,
    ProgressionImportSerializer,
    ValiderCorrespondanceImportSerializer,
)
from .service import ChampsAttendusImportService, ImportOfficielService
from .tasks import (
    ProgressionImportService,
    confirmer_import_task,
    supprimer_import_logiquement_task,
    valider_lignes_import_task,
)


class ImportOfficielViewSet(viewsets.ModelViewSet):
    """API des dossiers d'import officiel.

    Le frontend envoie le fichier puis suit le statut. Les traitements longs
    restent asynchrones via Celery : lecture des colonnes, validation des lignes,
    confirmation finale et suppression logique massive.
    """

    permission_classes = [PermissionImportOfficiel]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        params = self.request.query_params
        return ImportOfficielRepository.lister(
            session_id=params.get("session") or params.get("session_id"),
            type_source=params.get("type_source"),
            statut=params.get("statut"),
            recherche=params.get("q") or params.get("recherche"),
            date_debut=params.get("date_debut"),
            date_fin=params.get("date_fin"),
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ImportOfficielCreateSerializer
        if self.action == "valider_correspondance":
            return ValiderCorrespondanceImportSerializer
        if self.action == "annuler":
            return AnnulerImportSerializer
        if self.action == "list":
            return ImportOfficielListSerializer
        return ImportOfficielDetailSerializer

    @action(detail=False, methods=["get"], url_path="champs-attendus")
    def champs_attendus(self, request):
        """Retourne les champs attendus pour un type d'import.

        Le frontend s'en sert pour construire l'écran de correspondance des
        colonnes, au lieu d'inventer les règles métier comme un tableur en roue
        libre.
        """

        type_source = request.query_params.get("type_source")
        ChampsAttendusImportService.valider_type_source(type_source)
        donnees = ChampsAttendusTypeSourceSerializer.construire(type_source)
        return Response(donnees, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def progression(self, request, pk=None):
        """Retourne la progression temporaire stockée dans Redis/cache."""

        import_officiel = self.get_object()
        progression = ProgressionImportService.lire(import_officiel.id)
        donnees = {
            "import_id": import_officiel.id,
            "operation": progression.get("operation", ""),
            "pourcentage": progression.get("pourcentage", 0),
            "message": progression.get("message", ""),
            "updated_at": progression.get("updated_at", ""),
        }
        serializer = ProgressionImportSerializer(donnees)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="relancer-lecture")
    def relancer_lecture(self, request, pk=None):
        """Relance l'analyse asynchrone des colonnes détectées."""

        import_officiel = self.get_object()
        ImportOfficielService.planifier_lecture_colonnes(import_officiel)
        return Response(
            {
                "detail": "Lecture des colonnes relancée.",
                "import_id": import_officiel.id,
                "statut": import_officiel.statut,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"], url_path="valider-correspondance")
    def valider_correspondance(self, request, pk=None):
        """Valide la correspondance colonnes fichier -> champs FasoIM."""

        import_officiel = self.get_object()
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request, "import_id": import_officiel.id},
        )
        serializer.is_valid(raise_exception=True)
        import_actualise = serializer.save()
        return Response(
            ImportOfficielDetailSerializer(import_actualise, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="valider-lignes")
    def valider_lignes(self, request, pk=None):
        """Relance la validation asynchrone des lignes de l'import."""

        import_officiel = self.get_object()
        valider_lignes_import_task.delay(import_officiel.id)
        return Response(
            {"detail": "Validation des lignes lancée.", "import_id": import_officiel.id},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"])
    def confirmer(self, request, pk=None):
        """Lance la confirmation finale de l'import.

        La tâche est déjà exposée pour fixer le contrat API. La création réelle
        des immergés sera branchée après le module immerges.
        """

        import_officiel = self.get_object()
        acteur_id = getattr(request.user, "id", None)
        confirmer_import_task.delay(import_officiel.id, confirme_par_id=acteur_id)
        return Response(
            {"detail": "Confirmation de l'import lancée.", "import_id": import_officiel.id},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"])
    def annuler(self, request, pk=None):
        """Annule un import officiel."""

        import_officiel = self.get_object()
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request, "import_id": import_officiel.id},
        )
        serializer.is_valid(raise_exception=True)
        import_actualise = serializer.save()
        return Response(
            ImportOfficielDetailSerializer(import_actualise, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="supprimer-logiquement")
    def supprimer_logiquement(self, request, pk=None):
        """Lance la suppression logique massive de l'import et ses dépendances."""

        import_officiel = self.get_object()
        supprimer_import_logiquement_task.delay(import_officiel.id)
        return Response(
            {"detail": "Suppression logique lancée.", "import_id": import_officiel.id},
            status=status.HTTP_202_ACCEPTED,
        )

    def destroy(self, request, *args, **kwargs):
        """DELETE déclenche aussi la suppression logique asynchrone."""

        import_officiel = self.get_object()
        supprimer_import_logiquement_task.delay(import_officiel.id)
        return Response(status=status.HTTP_202_ACCEPTED)


class CorrespondanceColonneImportViewSet(viewsets.ReadOnlyModelViewSet):
    """Consultation des correspondances de colonnes d'un import."""

    serializer_class = CorrespondanceColonneImportSerializer
    permission_classes = [PermissionCorrespondanceColonneImport]

    def get_queryset(self):
        params = self.request.query_params
        queryset = CorrespondanceColonneImportRepository.actives()
        import_id = params.get("import_officiel") or params.get("import_officiel_id") or params.get("import_id")
        if import_id:
            queryset = queryset.filter(import_officiel_id=import_id)
        if params.get("champ_cible"):
            queryset = queryset.filter(champ_cible=params.get("champ_cible"))
        if params.get("colonne_source"):
            queryset = queryset.filter(colonne_source__icontains=params.get("colonne_source"))
        if params.get("confirmee") in {"true", "1", "oui"}:
            queryset = queryset.filter(confirmee=True)
        return queryset.order_by("import_officiel_id", "ordre", "champ_cible")


class LigneImportViewSet(viewsets.ReadOnlyModelViewSet):
    """Consultation et actions simples sur les lignes lues d'un import."""

    serializer_class = LigneImportSerializer
    permission_classes = [PermissionLigneImport]

    def get_queryset(self):
        params = self.request.query_params
        queryset = LigneImportRepository.actives()
        import_id = params.get("import_officiel") or params.get("import_officiel_id") or params.get("import_id")
        if import_id:
            queryset = queryset.filter(import_officiel_id=import_id)
        if params.get("statut"):
            queryset = queryset.filter(statut=params.get("statut"))
        if params.get("numero_ligne"):
            queryset = queryset.filter(numero_ligne=params.get("numero_ligne"))
        return queryset.order_by("import_officiel_id", "numero_ligne")

    @action(detail=True, methods=["patch"])
    def corriger(self, request, pk=None):
        """Enregistre une correction manuelle de ligne.

        La correction remet la ligne en attente. La validation complète reste
        relancée par Celery, pour éviter de refaire un mini-validateur bancal ici.
        """

        ligne = self.get_object()
        donnees_corrigees = request.data.get("donnees_corrigees") or request.data.get("donnees_normalisees")
        if not isinstance(donnees_corrigees, dict):
            return Response(
                {"donnees_corrigees": "Un objet JSON est attendu."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ligne.donnees_normalisees = donnees_corrigees
        ligne.statut = LigneImport.Statut.EN_ATTENTE
        ligne.message_statut = "Ligne corrigée manuellement. Revalidation nécessaire."
        ligne.save(update_fields=["donnees_normalisees", "statut", "message_statut", "updated_at"])
        return Response(self.get_serializer(ligne).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def ignorer(self, request, pk=None):
        """Marque une ligne comme ignorée."""

        ligne = self.get_object()
        message = request.data.get("message") or "Ligne ignorée manuellement."
        ligne.statut = LigneImport.Statut.IGNOREE
        ligne.message_statut = message
        ligne.save(update_fields=["statut", "message_statut", "updated_at"])
        return Response(self.get_serializer(ligne).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def revalider(self, request, pk=None):
        """Relance la validation de l'import parent de cette ligne."""

        ligne = self.get_object()
        valider_lignes_import_task.delay(ligne.import_officiel_id)
        return Response(
            {"detail": "Validation relancée pour l'import.", "import_id": ligne.import_officiel_id},
            status=status.HTTP_202_ACCEPTED,
        )


class ErreurImportViewSet(viewsets.ReadOnlyModelViewSet):
    """Consultation des erreurs détectées pendant la validation."""

    serializer_class = ErreurImportSerializer
    permission_classes = [PermissionErreurImport]

    def get_queryset(self):
        params = self.request.query_params
        queryset = ErreurImportRepository.actives()
        import_id = params.get("import_officiel") or params.get("import_officiel_id") or params.get("import_id")
        if import_id:
            queryset = queryset.filter(import_officiel_id=import_id)
        if params.get("ligne_import") or params.get("ligne_import_id"):
            queryset = queryset.filter(ligne_import_id=params.get("ligne_import") or params.get("ligne_import_id"))
        if params.get("gravite"):
            queryset = queryset.filter(gravite=params.get("gravite"))
        if params.get("type_erreur"):
            queryset = queryset.filter(type_erreur=params.get("type_erreur"))
        if params.get("champ_cible"):
            queryset = queryset.filter(champ_cible=params.get("champ_cible"))
        return queryset.order_by("import_officiel_id", "ligne_import__numero_ligne", "champ_cible", "id")
