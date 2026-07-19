from datetime import datetime, time, timedelta

from django.db import migrations
from django.utils import timezone


def reparer_evaluations(apps, schema_editor):
    Evaluation = apps.get_model("activites", "Evaluation")
    Seance = apps.get_model("activites", "Seance")

    for evaluation in Evaluation.objects.all().iterator():
        seance = None
        if evaluation.seance_id:
            seance = Seance.objects.filter(pk=evaluation.seance_id).first()
            if (
                seance
                and seance.session_id == evaluation.session_id
                and seance.centre_id == evaluation.centre_id
            ):
                continue

        date_evaluation = evaluation.date_evaluation
        if timezone.is_aware(date_evaluation):
            date_locale = timezone.localtime(date_evaluation)
        else:
            date_locale = date_evaluation

        seance = (
            Seance.objects.filter(
                session_id=evaluation.session_id,
                centre_id=evaluation.centre_id,
                date_seance=date_locale.date(),
                deleted_at__isnull=True,
            )
            .order_by("heure_debut", "id")
            .first()
        )

        if seance is None:
            debut = date_locale.time().replace(second=0, microsecond=0)
            fin_dt = datetime.combine(date_locale.date(), debut) + timedelta(hours=1)
            fin = fin_dt.time()
            if fin <= debut:
                fin = time(23, 59)

            statut = "TERMINEE" if evaluation.statut == "CLOTUREE" else "PLANIFIEE"
            feuille = "CLOTUREE" if evaluation.statut == "CLOTUREE" else "NON_OUVERTE"
            seance = Seance.objects.create(
                module_activite_id=None,
                session_id=evaluation.session_id,
                centre_id=evaluation.centre_id,
                titre=f"Séance évaluative — {evaluation.titre}",
                date_seance=date_locale.date(),
                heure_debut=debut,
                heure_fin=fin,
                lieu="À préciser",
                statut=statut,
                statut_feuille_presence=feuille,
                observations="Séance créée automatiquement lors de la migration des évaluations.",
            )

        evaluation.seance_id = seance.id
        evaluation.save(update_fields=["seance"])


class Migration(migrations.Migration):
    dependencies = [
        ("activites", "0003_alter_evaluation_seance_alter_seance_module_activite"),
    ]

    operations = [
        migrations.RunPython(reparer_evaluations, migrations.RunPython.noop),
    ]
