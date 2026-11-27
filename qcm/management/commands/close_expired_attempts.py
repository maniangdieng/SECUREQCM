from django.core.management.base import BaseCommand

from qcm.services import close_expired_attempts


class Command(BaseCommand):
    help = "Clôt les tentatives dont le temps est écoulé (à planifier, par exemple chaque minute)."

    def handle(self, *args, **options):
        count = close_expired_attempts()
        if options["verbosity"]:
            self.stdout.write(f"{count} tentative(s) clôturée(s).")
