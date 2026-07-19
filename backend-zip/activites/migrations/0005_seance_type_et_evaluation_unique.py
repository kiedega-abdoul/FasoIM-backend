from django.db import migrations, models
import django.db.models.deletion


def typer_et_dedoubler_evaluations(apps, schema_editor):
    Seance = apps.get_model("activites", "Seance")
    Evaluation = apps.get_model("activites", "Evaluation")

    groupes = {}
    for evaluation in Evaluation.objects.order_by("seance_id", "id"):
        groupes.setdefault(evaluation.seance_id, []).append(evaluation)

    for seance_id, evaluations in groupes.items():
        seance = Seance.objects.get(id=seance_id)
        seance.type_seance = "EVALUATION"
        seance.module_activite_id = None
        if not seance.titre:
            seance.titre = evaluations[0].titre or "Évaluation"
        seance.save(update_fields=["type_seance", "module_activite", "titre"])

        for index, evaluation in enumerate(evaluations[1:], start=2):
            clone = Seance.objects.create(
                module_activite_id=None,
                type_seance="EVALUATION",
                session_id=seance.session_id,
                centre_id=seance.centre_id,
                section_id=seance.section_id,
                groupe_id=seance.groupe_id,
                formateur_id=seance.formateur_id,
                titre=evaluation.titre or f"{seance.titre} {index}",
                date_seance=seance.date_seance,
                heure_debut=seance.heure_debut,
                heure_fin=seance.heure_fin,
                lieu=seance.lieu,
                statut=seance.statut,
                observations=seance.observations,
                statut_feuille_presence=seance.statut_feuille_presence,
                date_ouverture_presence=seance.date_ouverture_presence,
                date_validation_presence=seance.date_validation_presence,
                date_cloture_presence=seance.date_cloture_presence,
                presences_validees_par_id=seance.presences_validees_par_id,
            )
            evaluation.seance_id = clone.id
            evaluation.save(update_fields=["seance"])


class Migration(migrations.Migration):
    dependencies = [("activites", "0004_reparer_evaluations_seance")]
    operations = [
        migrations.AlterField(
            model_name="moduleactivite",
            name="code",
            field=models.CharField(blank=True, default="", max_length=60),
        ),
        migrations.AddField(
            model_name="seance",
            name="type_seance",
            field=models.CharField(
                choices=[
                    ("ACTIVITE", "Activité"),
                    ("EVALUATION", "Évaluation"),
                    ("CEREMONIE", "Cérémonie"),
                    ("REUNION", "Réunion"),
                    ("AUTRE", "Autre"),
                ],
                db_index=True,
                default="ACTIVITE",
                max_length=20,
            ),
        ),
        migrations.RunPython(
            typer_et_dedoubler_evaluations,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="seance",
            name="titre",
            field=models.CharField(max_length=180),
        ),
        migrations.AlterField(
            model_name="evaluation",
            name="seance",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="evaluation",
                to="activites.seance",
            ),
        ),
    ]
