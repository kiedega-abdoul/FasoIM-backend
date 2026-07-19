# Generated manually for FasoIM accounts perimeter correction.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_remove_affectationacteur_session_id_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="role",
            name="perimetre_autorise",
            field=models.CharField(
                choices=[
                    ("plateforme", "Plateforme"),
                    ("national", "National"),
                    ("region", "Région"),
                    ("centre", "Centre"),
                ],
                db_index=True,
                default="national",
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="affectationacteur",
            name="niveau_affectation",
            field=models.CharField(
                choices=[
                    ("plateforme", "Plateforme"),
                    ("national", "National"),
                    ("region", "Région"),
                    ("centre", "Centre"),
                ],
                db_index=True,
                default="national",
                max_length=30,
            ),
        ),
    ]
