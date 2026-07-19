from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sessions_app", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="parametresession",
            name="moyenne_minimum_attestation",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("10.00"),
                help_text="Moyenne minimale sur 20 lorsque les évaluations sont activées.",
                max_digits=5,
                validators=[
                    MinValueValidator(Decimal("0.00")),
                    MaxValueValidator(Decimal("20.00")),
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresession",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(moyenne_minimum_attestation__gte=0)
                    & models.Q(moyenne_minimum_attestation__lte=20)
                ),
                name="parametres_session_moyenne_0_20",
            ),
        ),
    ]
