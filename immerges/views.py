from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
)
from .permissions import (
    PermissionImmergeCentral,
    PermissionInscriptionVolontaire,
    PermissionSourceImmerge,
)
from .serializers import (
    ImmergeConcoursSerializer,
    ImmergeExamenSerializer,
    ImmergeSelectionneSerializer,
    ImmergeSerializer,
    InscriptionVolontaireSerializer,
)
from .service import ImmergeService, InscriptionVolontaireService
from .tasks import (
    ProgressionImmergeService,
    accepter_volontaires_en_lot_task,
    centraliser_source_immerge_task,
    centraliser_sources_importees_task,
    centraliser_volontaires_acceptes_task,
    changer_statut_immerges_en_lot_task,
    confirmer_import_vers_immerges_task,
    generer_codes_fasoim_manquants_task,
    regenerer_qr_codes_task,
    supprimer_immerges_session_task,
)


class SourceImmergeMixin:
    """Filtres communs des sources importées."""

    permission_classes = [PermissionSourceImmerge]

    def filtrer_queryset(self, queryset):
        import_officiel = self.request.query_params.get("import_officiel")
        session = self.request.query_params.get("session")
        statut_validation = self.request.query_params.get("statut_validation")

        if import_officiel:
            queryset = queryset.filter(import_officiel_id=import_officiel)
        if session:
            queryset = queryset.filter(import_officiel__session_id=session)
        if statut_validation:
            queryset = queryset.filter(statut_validation=statut_validation)

        return queryset

    @action(detail=True, methods=["post"], url_path="centraliser")
    def centraliser(self, request, pk=None):
        """Crée l'Immerge central depuis cette source."""

        source = self.get_object()
        immerge = self.creer_immerge_depuis_source(source)
        return Response(ImmergeSerializer(immerge).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="centraliser-lot-async")
    def centraliser_lot_async(self, request):
        """Lance la centralisation asynchrone des sources validées."""

        task = centraliser_sources_importees_task.delay(
            self.type_immerge_lot,
            import_officiel_id=request.data.get("import_officiel_id") or request.data.get("import_officiel"),
            session_id=request.data.get("session_id") or request.data.get("session"),
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)


class ImmergeExamenViewSet(SourceImmergeMixin, viewsets.ModelViewSet):
    serializer_class = ImmergeExamenSerializer
    type_immerge_lot = None

    def get_queryset(self):
        queryset = ImmergeExamen.objects.filter(deleted_at__isnull=True).select_related("import_officiel", "import_officiel__session")
        type_examen = self.request.query_params.get("type_examen")
        numero_pv = self.request.query_params.get("numero_pv")

        queryset = self.filtrer_queryset(queryset)

        if type_examen:
            queryset = queryset.filter(type_examen=type_examen)
            self.type_immerge_lot = type_examen
        if numero_pv:
            queryset = queryset.filter(numero_pv__icontains=numero_pv)

        return queryset.order_by("-id")

    def get_type_immerge_lot(self):
        return self.request.data.get("type_immerge") or self.request.query_params.get("type_examen") or Immerge.TypeImmerge.BAC

    @action(detail=False, methods=["post"], url_path="centraliser-lot-async")
    def centraliser_lot_async(self, request):
        task = centraliser_sources_importees_task.delay(
            request.data.get("type_immerge") or request.query_params.get("type_examen") or Immerge.TypeImmerge.BAC,
            import_officiel_id=request.data.get("import_officiel_id") or request.data.get("import_officiel"),
            session_id=request.data.get("session_id") or request.data.get("session"),
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    def creer_immerge_depuis_source(self, source):
        return ImmergeService.creer_depuis_examen(source)


class ImmergeConcoursViewSet(SourceImmergeMixin, viewsets.ModelViewSet):
    serializer_class = ImmergeConcoursSerializer
    type_immerge_lot = Immerge.TypeImmerge.CONCOURS

    def get_queryset(self):
        queryset = ImmergeConcours.objects.filter(deleted_at__isnull=True).select_related("import_officiel", "import_officiel__session")
        numero_recepisse = self.request.query_params.get("numero_recepisse")
        queryset = self.filtrer_queryset(queryset)

        if numero_recepisse:
            queryset = queryset.filter(numero_recepisse__icontains=numero_recepisse)

        return queryset.order_by("-id")

    def creer_immerge_depuis_source(self, source):
        return ImmergeService.creer_depuis_concours(source)


class ImmergeSelectionneViewSet(SourceImmergeMixin, viewsets.ModelViewSet):
    serializer_class = ImmergeSelectionneSerializer
    type_immerge_lot = Immerge.TypeImmerge.SELECTIONNE

    def get_queryset(self):
        queryset = ImmergeSelectionne.objects.filter(deleted_at__isnull=True).select_related("import_officiel", "import_officiel__session")
        matricule = self.request.query_params.get("matricule")
        reference_selection = self.request.query_params.get("reference_selection")
        queryset = self.filtrer_queryset(queryset)

        if matricule:
            queryset = queryset.filter(matricule__icontains=matricule)
        if reference_selection:
            queryset = queryset.filter(reference_selection__icontains=reference_selection)

        return queryset.order_by("-id")

    def creer_immerge_depuis_source(self, source):
        return ImmergeService.creer_depuis_selectionne(source)


class InscriptionVolontaireViewSet(viewsets.ModelViewSet):
    serializer_class = InscriptionVolontaireSerializer
    permission_classes = [PermissionInscriptionVolontaire]

    def get_queryset(self):
        queryset = InscriptionVolontaire.objects.filter(deleted_at__isnull=True).select_related("session", "traite_par")

        session = self.request.query_params.get("session")
        statut = self.request.query_params.get("statut_demande") or self.request.query_params.get("statut")
        code_suivi = self.request.query_params.get("code_suivi")

        if session:
            queryset = queryset.filter(session_id=session)
        if statut:
            queryset = queryset.filter(statut_demande=statut)
        if code_suivi:
            queryset = queryset.filter(code_suivi__iexact=code_suivi)

        return queryset.order_by("-id")

    @action(detail=True, methods=["post"], url_path="accepter")
    def accepter(self, request, pk=None):
        inscription = self.get_object()
        inscription = InscriptionVolontaireService.accepter(
            inscription,
            acteur=request.user,
            motif_decision=request.data.get("motif_decision", ""),
            creer_immerge=request.data.get("creer_immerge", True),
        )
        return Response(self.get_serializer(inscription).data)

    @action(detail=True, methods=["post"], url_path="rejeter")
    def rejeter(self, request, pk=None):
        inscription = self.get_object()
        inscription = InscriptionVolontaireService.rejeter(
            inscription,
            acteur=request.user,
            motif_decision=request.data.get("motif_decision", ""),
        )
        return Response(self.get_serializer(inscription).data)

    @action(detail=True, methods=["post"], url_path="annuler")
    def annuler(self, request, pk=None):
        inscription = self.get_object()
        inscription = InscriptionVolontaireService.annuler(
            inscription,
            motif_decision=request.data.get("motif_decision", ""),
        )
        return Response(self.get_serializer(inscription).data)

    @action(detail=False, methods=["post"], url_path="accepter-lot-async")
    def accepter_lot_async(self, request):
        task = accepter_volontaires_en_lot_task.delay(
            request.data.get("inscription_ids", []),
            acteur_id=request.user.id,
            motif_decision=request.data.get("motif_decision", ""),
            creer_immerge=request.data.get("creer_immerge", True),
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"], url_path="centraliser-acceptes-async")
    def centraliser_acceptes_async(self, request):
        task = centraliser_volontaires_acceptes_task.delay(
            session_id=request.data.get("session_id") or request.data.get("session"),
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)


class ImmergeViewSet(viewsets.ModelViewSet):
    serializer_class = ImmergeSerializer
    permission_classes = [PermissionImmergeCentral]

    def get_queryset(self):
        queryset = Immerge.objects.filter(deleted_at__isnull=True).select_related("session")

        session = self.request.query_params.get("session")
        type_immerge = self.request.query_params.get("type_immerge")
        statut_immerge = self.request.query_params.get("statut")
        code_fasoim = self.request.query_params.get("code_fasoim")

        if session:
            queryset = queryset.filter(session_id=session)
        if type_immerge:
            queryset = queryset.filter(type_immerge=type_immerge)
        if statut_immerge:
            queryset = queryset.filter(statut=statut_immerge)
        if code_fasoim:
            queryset = queryset.filter(code_fasoim__icontains=code_fasoim)

        return queryset.order_by("-id")

    @action(detail=False, methods=["post"], url_path="centraliser")
    def centraliser(self, request):
        type_immerge = request.data.get("type_immerge")
        source_id = request.data.get("source_id") or request.data.get("origine_id")

        if not type_immerge or not source_id:
            return Response(
                {"detail": "type_immerge et source_id sont obligatoires."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        source_id = int(source_id)

        if type_immerge in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
            from .repository import ImmergeExamenRepository

            source = ImmergeExamenRepository.get_by_id(source_id)
            immerge = ImmergeService.creer_depuis_examen(source)
        elif type_immerge == Immerge.TypeImmerge.CONCOURS:
            from .repository import ImmergeConcoursRepository

            source = ImmergeConcoursRepository.get_by_id(source_id)
            immerge = ImmergeService.creer_depuis_concours(source)
        elif type_immerge == Immerge.TypeImmerge.SELECTIONNE:
            from .repository import ImmergeSelectionneRepository

            source = ImmergeSelectionneRepository.get_by_id(source_id)
            immerge = ImmergeService.creer_depuis_selectionne(source)
        elif type_immerge == Immerge.TypeImmerge.VOLONTAIRE:
            from .repository import InscriptionVolontaireRepository

            source = InscriptionVolontaireRepository.get_by_id(source_id)
            immerge = ImmergeService.creer_depuis_volontaire(source)
        else:
            return Response({"detail": "type_immerge invalide."}, status=status.HTTP_400_BAD_REQUEST)

        return Response(self.get_serializer(immerge).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="centraliser-source-async")
    def centraliser_source_async(self, request):
        task = centraliser_source_immerge_task.delay(
            request.data.get("type_immerge"),
            request.data.get("source_id") or request.data.get("origine_id"),
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="changer-statut")
    def changer_statut(self, request, pk=None):
        immerge = self.get_object()
        statut_immerge = request.data.get("statut")
        immerge = ImmergeService.changer_statut(immerge, statut_immerge)
        return Response(self.get_serializer(immerge).data)

    @action(detail=False, methods=["post"], url_path="changer-statut-lot-async")
    def changer_statut_lot_async(self, request):
        task = changer_statut_immerges_en_lot_task.delay(
            request.data.get("immerge_ids", []),
            request.data.get("statut"),
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="generer-code")
    def generer_code(self, request, pk=None):
        immerge = self.get_object()
        immerge = ImmergeService.generer_code_si_absent(immerge)
        return Response(self.get_serializer(immerge).data)

    @action(detail=False, methods=["post"], url_path="generer-codes-manquants-async")
    def generer_codes_manquants_async(self, request):
        task = generer_codes_fasoim_manquants_task.delay(
            session_id=request.data.get("session_id") or request.data.get("session"),
            type_immerge=request.data.get("type_immerge"),
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"], url_path="regenerer-qr-codes-async")
    def regenerer_qr_codes_async(self, request):
        task = regenerer_qr_codes_task.delay(
            session_id=request.data.get("session_id") or request.data.get("session"),
            type_immerge=request.data.get("type_immerge"),
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"], url_path="supprimer-session-async")
    def supprimer_immerges_session_async(self, request):
        task = supprimer_immerges_session_task.delay(
            request.data.get("session_id") or request.data.get("session"),
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"], url_path="confirmer-import-async")
    def confirmer_import_async(self, request):
        task = confirmer_import_vers_immerges_task.delay(
            request.data.get("import_officiel_id") or request.data.get("import_officiel"),
            confirme_par_id=request.user.id,
        )
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["get"], url_path="progression")
    def progression(self, request):
        identifiant = request.query_params.get("identifiant")
        if not identifiant:
            return Response({"detail": "identifiant est obligatoire."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ProgressionImmergeService.lire(identifiant))

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        queryset = self.get_queryset()
        return Response(
            {
                "total": queryset.count(),
                "par_statut": list(queryset.values("statut").order_by("statut")),
                "par_type": list(queryset.values("type_immerge").order_by("type_immerge")),
            }
        )
