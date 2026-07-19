from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("activites", "0005_seance_type_et_evaluation_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="seance",
            name="date_debut_reelle",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="seance",
            name="date_fin_reelle",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
