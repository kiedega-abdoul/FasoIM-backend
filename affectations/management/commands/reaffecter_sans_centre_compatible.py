from django.core.management.base import BaseCommand, CommandError

from affectations.service import (
    AffectationRegionaleService,
    ValidationAffectationErreur,
)


class Command(BaseCommand):
    help = (
        "Simule ou applique la réaffectation régionale des immergés qui ne "
        "disposent plus d'aucun centre compatible dans leur région actuelle."
    )

    def add_arguments(self, parser):
        parser.add_argument("session_id", type=int)
        parser.add_argument(
            "--appliquer",
            action="store_true",
            help=(
                "Marque les anciennes affectations comme TRANSFEREE et crée "
                "les nouvelles propositions régionales. Sans cette option, "
                "la commande exécute uniquement une simulation."
            ),
        )

    def handle(self, *args, **options):
        try:
            resultat = (
                AffectationRegionaleService
                .proposer_reaffectations_sans_centre_compatible(
                    session_id=options["session_id"],
                    appliquer=options["appliquer"],
                )
            )
        except ValidationAffectationErreur as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Réaffectation terminée en mode " + resultat["mode"] + "."
            )
        )
        self.stdout.write(
            f"Affectations régionales sans centre : "
            f"{resultat['affectations_regionales_sans_centre']}"
        )
        self.stdout.write(
            f"Conservées dans leur région : "
            f"{resultat['conservees_dans_region_actuelle']}"
        )
        self.stdout.write(f"Bloquées : {resultat['bloquees']}")
        self.stdout.write(
            f"Nouvelles propositions : {resultat['reaffectations_proposees']}"
        )
        self.stdout.write(
            f"Sans destination compatible : "
            f"{len(resultat['sans_destination'])}"
        )
        self.stdout.write(
            f"Répartition par région : {resultat['repartition_par_region']}"
        )
        if not options["appliquer"]:
            self.stdout.write(
                self.style.WARNING(
                    "Simulation uniquement. Relancez avec --appliquer après "
                    "vérification des résultats."
                )
            )
