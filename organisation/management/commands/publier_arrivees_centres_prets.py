from django.core.management.base import BaseCommand, CommandError

from accounts.models import Acteur
from documents.models import PublicationOfficielle
from documents.service import PublicationService
from organisation.models import RegleOrganisationCentre


class Command(BaseCommand):
    help = (
        "Publie les informations d'arrivée des centres déjà marqués prêts "
        "mais dépourvus de publication officielle."
    )

    def add_arguments(self, parser):
        parser.add_argument("--session-id", type=int, required=True)
        parser.add_argument("--acteur-id", type=int)

    def handle(self, *args, **options):
        acteur_id = options.get("acteur_id")
        if acteur_id:
            acteur = Acteur.objects.filter(pk=acteur_id, is_active=True).first()
        else:
            acteur = Acteur.objects.filter(
                is_superuser=True,
                is_active=True,
            ).order_by("id").first()

        if acteur is None:
            raise CommandError(
                "Aucun acteur actif autorisé n'a été trouvé. "
                "Précisez --acteur-id."
            )

        regles = RegleOrganisationCentre.objects.filter(
            session_id=options["session_id"],
            statut=RegleOrganisationCentre.Statut.PRETE_PUBLICATION,
            deleted_at__isnull=True,
        ).select_related("centre")

        publiees = 0
        deja_publiees = 0
        erreurs = 0

        for regle in regles.iterator():
            existe = PublicationOfficielle.objects.filter(
                session_id=regle.session_id,
                centre_id=regle.centre_id,
                type_publication=(
                    PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE
                ),
                statut=PublicationOfficielle.Statut.PUBLIEE,
            ).exists()
            if existe:
                deja_publiees += 1
                continue

            try:
                PublicationService.soumettre_arrivee_centre(
                    session_id=regle.session_id,
                    centre_id=regle.centre_id,
                    acteur=acteur,
                )
            except Exception as exc:  # commande de réparation : poursuivre le lot
                erreurs += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Centre {regle.centre_id} ({regle.centre.nom}) : {exc}"
                    )
                )
            else:
                publiees += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Publié : {regle.centre.nom} (centre {regle.centre_id})"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Terminé — "
                f"publiées={publiees}, "
                f"déjà publiées={deja_publiees}, "
                f"erreurs={erreurs}."
            )
        )
