from __future__ import annotations

import hashlib
import json
import logging
import time
from ipaddress import ip_address
from typing import Any

from django.db import transaction

from .models import JournalAction


logger = logging.getLogger(__name__)


class JournalActionService:
    """Point d'entrée unique pour créer les journaux immuables FasoIM."""

    CHAMPS_SENSIBLES = {
        "password",
        "mot_de_passe",
        "new_password",
        "old_password",
        "token",
        "access",
        "refresh",
        "authorization",
        "otp",
        "secret",
        "secret_key",
        "cle_privee",
        "numero_cnib",
        "date_naissance",
        "diagnostic",
        "observation_medicale",
        "observations_medicales",
        "document_medical",
        "signature",
        "cachet",
    }

    @staticmethod
    def identifiant(objet):
        if objet is None:
            return None
        return getattr(objet, "pk", objet)

    @classmethod
    def masquer_donnees(cls, valeur: Any, *, cle: str = ""):
        if cle.lower() in cls.CHAMPS_SENSIBLES:
            return "[MASQUE]"
        if valeur is None or isinstance(valeur, (bool, int, float)):
            return valeur
        if isinstance(valeur, str):
            return valeur if len(valeur) <= 2000 else f"{valeur[:2000]}...[TRONQUE]"
        if isinstance(valeur, dict):
            return {
                str(k): cls.masquer_donnees(v, cle=str(k))
                for k, v in list(valeur.items())[:200]
            }
        if isinstance(valeur, (list, tuple, set)):
            return [cls.masquer_donnees(v) for v in list(valeur)[:200]]
        return str(valeur)

    @staticmethod
    def empreinte_identifiant(valeur):
        texte = str(valeur or "").strip()
        return hashlib.sha256(texte.encode("utf-8")).hexdigest() if texte else ""

    @staticmethod
    def extraire_ip(request):
        if request is None:
            return None
        valeur = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        valeur = valeur or request.META.get("REMOTE_ADDR")
        if not valeur:
            return None
        try:
            return str(ip_address(valeur))
        except ValueError:
            return None

    @staticmethod
    def _infos_objet(objet):
        if objet is None:
            return "", None, ""
        identifiant = getattr(objet, "pk", None)
        type_objet = objet.__class__.__name__ if not isinstance(objet, str) else objet
        reference = ""
        for champ in ("code", "code_fasoim", "numero", "reference", "uuid_evenement"):
            valeur = getattr(objet, champ, None)
            if valeur:
                reference = str(valeur)
                break
        return type_objet, identifiant, reference

    @classmethod
    def journaliser(
        cls,
        *,
        code_action,
        module_source,
        resultat,
        origine=None,
        canal=None,
        acteur=None,
        immerge=None,
        session=None,
        region=None,
        centre=None,
        objet=None,
        objet_type="",
        objet_id=None,
        objet_reference="",
        motif="",
        contexte=None,
        request=None,
        task_id="",
        duree_ms=None,
        strict=False,
    ):
        try:
            type_detecte, id_detecte, reference_detectee = cls._infos_objet(objet)
            user = getattr(request, "user", None) if request is not None else None
            if acteur is None and user is not None and getattr(user, "is_authenticated", False):
                acteur = user

            if origine is None:
                if task_id:
                    origine = JournalAction.Origine.CELERY
                elif immerge is not None:
                    origine = JournalAction.Origine.IMMERGE
                elif acteur is not None:
                    origine = JournalAction.Origine.ACTEUR
                elif request is not None:
                    origine = JournalAction.Origine.API_PUBLIQUE
                else:
                    origine = JournalAction.Origine.SYSTEME

            if canal is None:
                if origine == JournalAction.Origine.CELERY:
                    canal = JournalAction.Canal.CELERY
                elif origine in {JournalAction.Origine.IMMERGE, JournalAction.Origine.API_PUBLIQUE}:
                    canal = JournalAction.Canal.PORTAIL_PUBLIC
                elif request is not None:
                    canal = JournalAction.Canal.API
                else:
                    canal = JournalAction.Canal.SYSTEME

            if centre is None and objet is not None:
                centre = getattr(objet, "centre", None)
            if region is None:
                region = getattr(objet, "region", None) if objet is not None else None
                if region is None and centre is not None:
                    region = getattr(centre, "region", None)
            if session is None and objet is not None:
                session = getattr(objet, "session", None)

            journal = JournalAction.objects.create(
                origine=origine,
                resultat=resultat,
                canal=canal,
                acteur_id=cls.identifiant(acteur),
                immerge_id=cls.identifiant(immerge),
                session_id=cls.identifiant(session),
                region_id=cls.identifiant(region),
                centre_id=cls.identifiant(centre),
                code_action=str(code_action).strip()[:140],
                module_source=str(module_source).strip()[:80],
                motif=str(motif or "")[:5000],
                objet_type=str(objet_type or type_detecte)[:120],
                objet_id=objet_id if objet_id is not None else id_detecte,
                objet_reference=str(objet_reference or reference_detectee)[:180],
                contexte=cls.masquer_donnees(contexte or {}),
                adresse_ip=cls.extraire_ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT", "")[:500] if request else ""),
                methode_http=(request.method[:12] if request else ""),
                chemin_api=(request.path[:500] if request else ""),
                statut_http=getattr(getattr(request, "_audit_response", None), "status_code", None),
                duree_ms=duree_ms,
                task_id=str(task_id or "")[:80],
            )
            if request is not None:
                request._audit_action_enregistree = True
            return journal
        except Exception as exc:
            if exc.__class__.__name__ != "DatabaseOperationForbidden":
                logger.exception("Échec de journalisation de l'action %s", code_action)
            if strict:
                raise
            return None

    @classmethod
    def journaliser_tentative(cls, **kwargs):
        return cls.journaliser(resultat=JournalAction.Resultat.TENTATIVE, **kwargs)

    @classmethod
    def journaliser_succes(cls, **kwargs):
        return cls.journaliser(resultat=JournalAction.Resultat.SUCCES, **kwargs)

    @classmethod
    def journaliser_refus(cls, **kwargs):
        return cls.journaliser(resultat=JournalAction.Resultat.REFUS, **kwargs)

    @classmethod
    def journaliser_echec(cls, **kwargs):
        return cls.journaliser(resultat=JournalAction.Resultat.ECHEC, **kwargs)

    @classmethod
    def journaliser_consultation_immerge(
        cls,
        *,
        immerge=None,
        code_action="consulter_affectation_publique",
        resultat=JournalAction.Resultat.SUCCES,
        session=None,
        region=None,
        centre=None,
        request=None,
        identifiant_saisi=None,
        informations_consultees=None,
        motif="",
    ):
        contexte = {"informations_consultees": informations_consultees or []}
        if identifiant_saisi:
            contexte.update(
                {
                    "empreinte_identifiant": cls.empreinte_identifiant(identifiant_saisi),
                    "identifiant_masque": f"***{str(identifiant_saisi)[-4:]}",
                }
            )
        return cls.journaliser(
            code_action=code_action,
            module_source="documents",
            resultat=resultat,
            origine=JournalAction.Origine.IMMERGE if immerge else JournalAction.Origine.API_PUBLIQUE,
            canal=JournalAction.Canal.PORTAIL_PUBLIC,
            immerge=immerge,
            session=session,
            region=region,
            centre=centre,
            motif=motif,
            contexte=contexte,
            request=request,
        )

    @classmethod
    def journaliser_information_immerge(
        cls,
        *,
        code_action="envoyer_information_immerge",
        resultat,
        immerge=None,
        session=None,
        region=None,
        centre=None,
        canal=JournalAction.Canal.EMAIL,
        contexte=None,
        motif="",
        task_id="",
    ):
        return cls.journaliser(
            code_action=code_action,
            module_source="notifications",
            resultat=resultat,
            origine=JournalAction.Origine.CELERY if task_id else JournalAction.Origine.SYSTEME,
            canal=canal,
            immerge=immerge,
            session=session,
            region=region,
            centre=centre,
            contexte=contexte,
            motif=motif,
            task_id=task_id,
        )

    @classmethod
    def journaliser_telechargement_attestation(
        cls,
        *,
        immerge,
        attestation,
        resultat,
        request=None,
        contexte=None,
        motif="",
    ):
        return cls.journaliser(
            code_action="telecharger_attestation",
            module_source="documents",
            resultat=resultat,
            origine=JournalAction.Origine.IMMERGE,
            canal=JournalAction.Canal.PORTAIL_PUBLIC,
            immerge=immerge,
            session=getattr(attestation, "session", None),
            region=getattr(attestation, "region", None),
            centre=getattr(attestation, "centre", None),
            objet=attestation,
            contexte=contexte,
            motif=motif,
            request=request,
        )

    @classmethod
    def journaliser_export(
        cls,
        *,
        acteur,
        code_action,
        resultat,
        objet=None,
        session=None,
        region=None,
        centre=None,
        contexte=None,
        motif="",
        request=None,
        task_id="",
    ):
        return cls.journaliser(
            code_action=code_action,
            module_source="documents" if "rapport" in code_action else "audit",
            resultat=resultat,
            origine=JournalAction.Origine.CELERY if task_id else JournalAction.Origine.ACTEUR,
            canal=JournalAction.Canal.EXPORT,
            acteur=acteur,
            objet=objet,
            session=session,
            region=region,
            centre=centre,
            contexte=contexte,
            motif=motif,
            request=request,
            task_id=task_id,
        )


class AuditMiddleware:
    """Journalise les requêtes API sans exposer les corps ni les secrets.

    Les services métier peuvent créer une entrée plus précise et marquer la
    requête. Le middleware sert alors de filet de sécurité pour les actions non
    encore branchées explicitement.
    """

    EXCLUSIONS = ("/api/schema/", "/api/docs/", "/api/redoc/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        debut = time.monotonic()
        try:
            response = self.get_response(request)
        except Exception as exc:
            if self._doit_journaliser(request):
                JournalActionService.journaliser_echec(
                    code_action=self._code_action(request),
                    module_source=self._module_source(request),
                    request=request,
                    motif=exc.__class__.__name__,
                    contexte={"exception": str(exc)[:500]},
                    duree_ms=int((time.monotonic() - debut) * 1000),
                )
            raise

        request._audit_response = response
        if self._doit_journaliser(request) and not getattr(request, "_audit_action_enregistree", False):
            resultat = self._resultat_http(response.status_code)
            JournalActionService.journaliser(
                code_action=self._code_action(request),
                module_source=self._module_source(request),
                resultat=resultat,
                request=request,
                motif="Requête API journalisée automatiquement.",
                contexte={"statut_http": response.status_code},
                duree_ms=int((time.monotonic() - debut) * 1000),
            )
        return response

    def _doit_journaliser(self, request):
        est_cible = request.path.startswith("/api/") or request.path.startswith("/admin/")
        return est_cible and not request.path.startswith(self.EXCLUSIONS)

    @staticmethod
    def _module_source(request):
        morceaux = [m for m in request.path.split("/") if m]
        return (morceaux[1] if len(morceaux) > 1 else "api")[:80]

    @staticmethod
    def _code_action(request):
        correspondance = getattr(request, "resolver_match", None)
        nom = getattr(correspondance, "view_name", "") if correspondance else ""
        nom = str(nom or request.path.strip("/").replace("/", "_"))
        return f"api_{request.method.lower()}_{nom}"[:140]

    @staticmethod
    def _resultat_http(statut):
        if 200 <= statut < 400:
            return JournalAction.Resultat.SUCCES
        if statut in {401, 403, 404, 405, 429}:
            return JournalAction.Resultat.REFUS
        return JournalAction.Resultat.ECHEC
