from __future__ import annotations

import csv
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from openpyxl import Workbook

from accounts.models import Acteur

from .models import JournalAction
from .repository import JournalActionRepository
from .service import JournalActionService


EXPORT_TTL = 24 * 60 * 60


def cle_progression(task_id):
    return f"audit:export:{task_id}"


def enregistrer_progression(task_id, **valeurs):
    actuel = cache.get(cle_progression(task_id), {})
    actuel.update(valeurs)
    actuel["updated_at"] = timezone.now().isoformat()
    cache.set(cle_progression(task_id), actuel, EXPORT_TTL)
    return actuel


@shared_task(bind=True, name="audit.generer_export")
def generer_export_audit_task(self, *, acteur_id, filtres=None, format_export="CSV"):
    task_id = self.request.id
    acteur = Acteur.objects.filter(id=acteur_id, deleted_at__isnull=True).first()
    if not acteur:
        return enregistrer_progression(
            task_id,
            statut="ECHEC",
            progression=100,
            erreur="Acteur demandeur introuvable.",
        )

    enregistrer_progression(
        task_id,
        statut="EN_COURS",
        progression=5,
        acteur_id=acteur.id,
        format=format_export,
    )
    try:
        queryset = JournalActionRepository.visibles_par_acteur(
            acteur,
            code_permission="exporter_journaux_audit",
        )
        queryset = JournalActionRepository.filtrer(queryset, filtres or {})
        total = queryset.count()

        dossier = Path(settings.MEDIA_ROOT) / "audit_exports"
        dossier.mkdir(parents=True, exist_ok=True)
        extension = "xlsx" if format_export.upper() == "XLSX" else "csv"
        nom_fichier = f"audit_{timezone.now():%Y%m%d_%H%M%S}_{task_id}.{extension}"
        chemin = dossier / nom_fichier

        entetes = [
            "id",
            "date",
            "origine",
            "resultat",
            "canal",
            "code_action",
            "module",
            "acteur_id",
            "immerge_id",
            "session_id",
            "region_id",
            "centre_id",
            "objet_type",
            "objet_id",
            "objet_reference",
            "motif",
        ]

        if extension == "csv":
            with chemin.open("w", newline="", encoding="utf-8-sig") as fichier:
                writer = csv.writer(fichier)
                writer.writerow(entetes)
                for index, journal in enumerate(queryset.iterator(chunk_size=1000), start=1):
                    writer.writerow(_ligne_export(journal))
                    if total and index % 1000 == 0:
                        enregistrer_progression(
                            task_id,
                            progression=min(95, 5 + int(index * 90 / total)),
                        )
        else:
            classeur = Workbook(write_only=True)
            feuille = classeur.create_sheet("Audit")
            feuille.append(entetes)
            for index, journal in enumerate(queryset.iterator(chunk_size=1000), start=1):
                feuille.append(_ligne_export(journal))
                if total and index % 1000 == 0:
                    enregistrer_progression(
                        task_id,
                        progression=min(95, 5 + int(index * 90 / total)),
                    )
            classeur.save(chemin)

        resultat = enregistrer_progression(
            task_id,
            statut="TERMINE",
            progression=100,
            acteur_id=acteur.id,
            format=format_export.upper(),
            nom_fichier=nom_fichier,
            chemin=str(chemin),
            total_lignes=total,
            erreur="",
        )
        JournalActionService.journaliser_export(
            acteur=acteur,
            code_action="exporter_journaux_audit",
            resultat=JournalAction.Resultat.SUCCES,
            contexte={"format": format_export.upper(), "total_lignes": total},
            task_id=task_id,
        )
        return resultat
    except Exception as exc:
        JournalActionService.journaliser_export(
            acteur=acteur,
            code_action="exporter_journaux_audit",
            resultat=JournalAction.Resultat.ECHEC,
            motif=str(exc)[:1000],
            task_id=task_id,
        )
        return enregistrer_progression(
            task_id,
            statut="ECHEC",
            progression=100,
            acteur_id=acteur.id,
            erreur=str(exc)[:1000],
        )


def _ligne_export(journal):
    return [
        journal.id,
        journal.created_at.isoformat(),
        journal.origine,
        journal.resultat,
        journal.canal,
        journal.code_action,
        journal.module_source,
        journal.acteur_id or "",
        journal.immerge_id or "",
        journal.session_id or "",
        journal.region_id or "",
        journal.centre_id or "",
        journal.objet_type,
        journal.objet_id or "",
        journal.objet_reference,
        journal.motif,
    ]
