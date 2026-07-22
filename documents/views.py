from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import JournalAction
from audit.service import JournalActionService

from .models import DocumentGenere, PublicationOfficielle
from .permissions import EstActeurDocumentsActif, PermissionDocuments
from .repository import (
    DocumentGenereRepository,
    PublicationOfficielleRepository,
    ResultatFinalRepository,
)
from .serializers import (
    CentreActionSerializer,
    ConsultationArriveeSerializer,
    DocumentGenereSerializer,
    GenererRapportSerializer,
    ImmergeActionSerializer,
    PublicationOfficielleSerializer,
    PublierSessionSerializer,
    RejetPublicationSerializer,
    ResultatFinalSerializer,
    VerificationAttestationSerializer,
    ValidationAttestationsLotSerializer,
    StatistiquesAttestationsRegionSerializer,
)
from .service import (
    AttestationPubliqueService,
    AttestationService,
    DocumentArriveeService,
    IdentiteImmergeService,
    InformationsArriveeService,
    GenerationFichierService,
    PublicationService,
    SessionClotureService,
    ValidationDocumentsErreur,
    WorkflowAutomatiqueAttestationService,
)
from .tasks import (
    calculer_resultats_centre_task,
    cle_progression,
    generer_attestations_centre_task,
    generer_rapport_task,
    publier_session_task,
    signer_attestations_region_task,
)
from accounts.access_context import obtenir_affectation_courante_id
from django.core.cache import cache
from sessions_app.models import SessionImmersion


class PaginationDocuments(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


def _detail_exception(exc):
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    if hasattr(exc, "messages"):
        return exc.messages
    return str(exc)


def _lever(exc):
    raise ValidationError(_detail_exception(exc))


class ResultatFinalViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EstActeurDocumentsActif, PermissionDocuments]
    serializer_class = ResultatFinalSerializer
    pagination_class = PaginationDocuments
    permission_code_map = {
        "list": "consulter_resultats_finaux",
        "retrieve": "consulter_resultats_finaux",
        "statistiques": "consulter_resultats_finaux",
        "calculer_centre": "calculer_resultats_finaux",
        "valider_centre": "valider_resultats_centre",
    }

    def get_queryset(self):
        queryset = ResultatFinalRepository.visibles_par_acteur(self.request.user)
        return ResultatFinalRepository.filtrer(queryset, self.request.query_params)

    @action(detail=False, methods=["get"], url_path="statistiques")
    def statistiques(self, request):
        queryset = self.get_queryset()
        return Response(ResultatFinalRepository.statistiques(queryset))

    @action(detail=False, methods=["post"], url_path="calculer-centre")
    def calculer_centre(self, request):
        serializer = CentreActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = calculer_resultats_centre_task.delay(
            session_id=serializer.validated_data["session_id"],
            centre_id=serializer.validated_data["centre_id"],
            acteur_id=request.user.id,
            affectation_acteur_id=obtenir_affectation_courante_id(),
        )
        return Response({"task_id": resultat.id, "statut": "EN_ATTENTE"}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"], url_path="valider-centre")
    def valider_centre(self, request):
        from .service import EligibiliteAttestationService

        serializer = CentreActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            resultat = EligibiliteAttestationService.valider_centre(
                session_id=serializer.validated_data["session_id"],
                centre_id=serializer.validated_data["centre_id"],
                acteur=request.user,
            )
        except (DjangoValidationError, ValidationDocumentsErreur) as exc:
            _lever(exc)
        return Response(resultat)


class PublicationOfficielleViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EstActeurDocumentsActif, PermissionDocuments]
    serializer_class = PublicationOfficielleSerializer
    pagination_class = PaginationDocuments
    permission_code_map = {
        "list": "consulter_publications",
        "retrieve": "consulter_publications",
        "soumettre_arrivee": "soumettre_publication_centre",
        "soumettre_attestations": "soumettre_publication_centre",
        "valider_region": "valider_publication_region",
        "signer_attestations": "signer_attestations_region",
        "rejeter_region": "rejeter_publication_region",
        "publier_session": "publier_documents_session",
        "valider_attestations": "valider_publication_region",
        "valider_attestations_lot": "valider_publication_region",
        "statistiques_attestations_region": "consulter_resultats_finaux",
    }

    def get_queryset(self):
        queryset = PublicationOfficielleRepository.visibles_par_acteur(self.request.user)
        return PublicationOfficielleRepository.filtrer(queryset, self.request.query_params)

    @action(detail=False, methods=["post"], url_path="soumettre-arrivee")
    def soumettre_arrivee(self, request):
        serializer = CentreActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            publication = PublicationService.soumettre_arrivee_centre(
                **serializer.validated_data,
                acteur=request.user,
            )
        except (DjangoValidationError, ValidationDocumentsErreur) as exc:
            _lever(exc)
        return Response(self.get_serializer(publication).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="soumettre-attestations")
    def soumettre_attestations(self, request):
        serializer = CentreActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            publication = PublicationService.soumettre_attestations_centre(
                **serializer.validated_data,
                acteur=request.user,
            )
        except (DjangoValidationError, ValidationDocumentsErreur) as exc:
            _lever(exc)
        return Response(self.get_serializer(publication).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="valider-region")
    def valider_region(self, request, pk=None):
        publication = self.get_object()
        if publication.type_publication == PublicationOfficielle.TypePublication.ATTESTATIONS:
            resultat = signer_attestations_region_task.delay(
                publication_id=publication.id,
                acteur_id=request.user.id,
            )
            return Response(
                {"task_id": resultat.id, "statut": "EN_ATTENTE"},
                status=status.HTTP_202_ACCEPTED,
            )
        try:
            resultat = PublicationService.valider_region(
                publication_id=publication.id, acteur=request.user
            )
        except (DjangoValidationError, ValidationDocumentsErreur) as exc:
            _lever(exc)
        return Response(self.get_serializer(resultat).data)

    @action(detail=True, methods=["post"], url_path="signer-attestations")
    def signer_attestations(self, request, pk=None):
        publication = self.get_object()
        resultat = signer_attestations_region_task.delay(
            publication_id=publication.id,
            acteur_id=request.user.id,
        )
        return Response(
            {"task_id": resultat.id, "statut": "EN_ATTENTE"},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"], url_path="valider-attestations")
    def valider_attestations(self, request, pk=None):
        try:
            resultat = WorkflowAutomatiqueAttestationService.valider_et_publier(
                publication_id=pk, acteur=request.user
            )
        except (DjangoValidationError, ValidationDocumentsErreur) as exc:
            _lever(exc)
        return Response(resultat)

    @action(detail=False, methods=["post"], url_path="valider-attestations-lot")
    def valider_attestations_lot(self, request):
        serializer = ValidationAttestationsLotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = WorkflowAutomatiqueAttestationService.valider_lot(
            publication_ids=serializer.validated_data["publication_ids"],
            acteur=request.user,
        )
        return Response(resultat)

    @action(detail=False, methods=["get"], url_path="statistiques-attestations-region")
    def statistiques_attestations_region(self, request):
        serializer = StatistiquesAttestationsRegionSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            resultat = WorkflowAutomatiqueAttestationService.statistiques_region(
                acteur=request.user, **serializer.validated_data
            )
        except (DjangoValidationError, ValidationDocumentsErreur) as exc:
            _lever(exc)
        return Response(resultat)

    @action(detail=True, methods=["post"], url_path="rejeter-region")
    def rejeter_region(self, request, pk=None):
        serializer = RejetPublicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            publication = PublicationService.rejeter_region(
                publication_id=pk,
                acteur=request.user,
                motif=serializer.validated_data["motif"],
            )
        except (DjangoValidationError, ValidationDocumentsErreur) as exc:
            _lever(exc)
        return Response(self.get_serializer(publication).data)

    @action(detail=False, methods=["post"], url_path="publier-session")
    def publier_session(self, request):
        serializer = PublierSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = publier_session_task.delay(
            session_id=serializer.validated_data["session_id"],
            type_publication=serializer.validated_data["type_publication"],
            acteur_id=request.user.id,
        )
        return Response(
            {"task_id": resultat.id, "statut": "EN_ATTENTE"},
            status=status.HTTP_202_ACCEPTED,
        )


class DocumentGenereViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EstActeurDocumentsActif, PermissionDocuments]
    serializer_class = DocumentGenereSerializer
    pagination_class = PaginationDocuments
    permission_code_map = {
        "list": "consulter_documents",
        "retrieve": "consulter_documents",
        "generer_attestations": "generer_attestations",
        "generer_fiche_arrivee": "generer_rapports",
        "generer_rapport": "generer_rapports",
        "telecharger": "telecharger_document",
        "progression": "consulter_documents",
    }

    def get_queryset(self):
        queryset = DocumentGenereRepository.visibles_par_acteur(self.request.user)
        return DocumentGenereRepository.filtrer(queryset, self.request.query_params)

    @action(detail=False, methods=["post"], url_path="generer-attestations")
    def generer_attestations(self, request):
        serializer = CentreActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = generer_attestations_centre_task.delay(
            session_id=serializer.validated_data["session_id"],
            centre_id=serializer.validated_data["centre_id"],
            acteur_id=request.user.id,
            affectation_acteur_id=obtenir_affectation_courante_id(),
        )
        return Response({"task_id": resultat.id, "statut": "EN_ATTENTE"}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"], url_path="generer-fiche-arrivee")
    def generer_fiche_arrivee(self, request):
        serializer = ImmergeActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            document = DocumentArriveeService.generer_fiche(
                immerge_id=serializer.validated_data["immerge_id"],
                acteur=request.user,
            )
        except (DjangoValidationError, ValidationDocumentsErreur) as exc:
            _lever(exc)
        return Response(self.get_serializer(document).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="generer-rapport")
    def generer_rapport(self, request):
        serializer = GenererRapportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = generer_rapport_task.delay(
            acteur_id=request.user.id,
            **serializer.validated_data,
        )
        return Response({"task_id": resultat.id, "statut": "EN_ATTENTE"}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"], url_path="telecharger")
    def telecharger(self, request, pk=None):
        document = self.get_object()
        if not document.est_telechargeable:
            return Response({"detail": "Document indisponible."}, status=404)
        if not GenerationFichierService.verifier_integrite(document):
            JournalActionService.journaliser_echec(
                code_action="telecharger_document_interne",
                module_source="documents",
                acteur=request.user,
                session=document.session,
                region=document.region,
                centre=document.centre,
                objet=document,
                request=request,
                motif="Intégrité du document invalide.",
                contexte={"numero_document": document.numero_document},
            )
            return Response({"detail": "L'intégrité du document est invalide."}, status=409)
        try:
            fichier = document.fichier.open("rb")
        except OSError:
            return Response({"detail": "Le fichier n'existe plus."}, status=404)
        JournalActionService.journaliser_succes(
            code_action="telecharger_document_interne",
            module_source="documents",
            acteur=request.user,
            session=document.session,
            region=document.region,
            centre=document.centre,
            objet=document,
            request=request,
            contexte={"type_document": document.type_document, "numero_document": document.numero_document},
        )
        return FileResponse(fichier, as_attachment=True, filename=document.nom_fichier)

    @action(detail=False, methods=["get"], url_path=r"progression/(?P<task_id>[0-9a-f-]+)")
    def progression(self, request, task_id=None):
        donnees = cache.get(cle_progression(task_id))
        if not donnees:
            return Response({"detail": "Tâche introuvable ou expirée."}, status=404)
        if not request.user.is_superuser and donnees.get("acteur_id") not in (None, request.user.id):
            return Response({"detail": "Cette tâche ne vous appartient pas."}, status=403)
        return Response(donnees)


class EtatClotureSessionView(APIView):
    permission_classes = [EstActeurDocumentsActif, PermissionDocuments]
    action_code = "verifier_cloture"
    permission_code_map = {"verifier_cloture": "verifier_cloture_session"}

    def get(self, request, session_id):
        try:
            session = SessionImmersion.objects.select_related("parametres").get(id=session_id, deleted_at__isnull=True)
            etat = SessionClotureService.verifier(session)
        except (SessionImmersion.DoesNotExist, DjangoValidationError, ValidationDocumentsErreur) as exc:
            _lever(exc)
        return Response(etat.en_dict())


class ConsultationArriveePubliqueView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ConsultationArriveeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adresse_ip = request.META.get("REMOTE_ADDR", "")
        try:
            InformationsArriveeService.verifier_limite(adresse_ip)
            immerge = IdentiteImmergeService.rechercher_public(**serializer.validated_data)
            if immerge is None:
                return Response({"detail": "Informations introuvables ou non publiées."}, status=404)
            donnees = InformationsArriveeService.construire(immerge, request=request)
        except (DjangoValidationError, ValidationDocumentsErreur):
            return Response({"detail": "Informations introuvables ou non publiées."}, status=404)
        return Response(donnees)


class ConsultationAttestationPubliqueView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ConsultationArriveeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adresse_ip = request.META.get("REMOTE_ADDR", "")
        try:
            InformationsArriveeService.verifier_limite(
                adresse_ip, usage="consultation_attestation"
            )
        except ValidationDocumentsErreur:
            return Response(
                {"detail": "Trop de tentatives. Veuillez réessayer plus tard."},
                status=429,
            )

        try:
            immerge = IdentiteImmergeService.rechercher_public(
                **serializer.validated_data
            )
            if immerge is None:
                return Response(
                    {"detail": "Attestation introuvable ou non publiée."},
                    status=404,
                )
            donnees = AttestationPubliqueService.consulter_immerge(
                immerge=immerge, request=request
            )
        except (DjangoValidationError, ValidationDocumentsErreur):
            return Response(
                {"detail": "Attestation introuvable ou non publiée."},
                status=404,
            )
        return Response(donnees)


class VerificationAttestationPubliqueView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerificationAttestationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            InformationsArriveeService.verifier_limite(
                request.META.get("REMOTE_ADDR", ""), usage="verification_attestation"
            )
        except ValidationDocumentsErreur:
            return Response({"detail": "Trop de tentatives."}, status=429)
        resultat = AttestationPubliqueService.verifier(
            **serializer.validated_data,
            request=request,
        )
        return Response(resultat, status=200 if resultat.get("valide") else 404)


class TelechargementAttestationPubliqueView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, code):
        try:
            InformationsArriveeService.verifier_limite(
                request.META.get("REMOTE_ADDR", ""), usage="telechargement_attestation"
            )
        except ValidationDocumentsErreur:
            return Response({"detail": "Trop de tentatives."}, status=429)
        document = DocumentGenereRepository.get_par_code_verification(code)
        if (
            document is None
            or document.type_document != DocumentGenere.TypeDocument.ATTESTATION
            or document.statut != DocumentGenere.Statut.PUBLIE
            or not document.fichier
            or not document.signature_appliquee
            or not document.cachet_applique
        ):
            return Response({"detail": "Attestation indisponible."}, status=404)
        if not GenerationFichierService.verifier_integrite(document):
            JournalActionService.journaliser_telechargement_attestation(
                immerge=document.immerge,
                attestation=document,
                resultat=JournalAction.Resultat.REFUS,
                request=request,
                contexte={
                    "numero_document": document.numero_document,
                    "motif": "INTEGRITE_INVALIDE",
                },
            )
            return Response({"detail": "L'intégrité de l'attestation est invalide."}, status=409)
        try:
            fichier = document.fichier.open("rb")
        except OSError:
            return Response({"detail": "Attestation indisponible."}, status=404)
        JournalActionService.journaliser_telechargement_attestation(
            immerge=document.immerge,
            attestation=document,
            resultat=JournalAction.Resultat.SUCCES,
            request=request,
            contexte={"numero_document": document.numero_document},
        )
        return FileResponse(fichier, as_attachment=True, filename=document.nom_fichier)
