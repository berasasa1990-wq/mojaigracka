import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied
from django.views.decorators.debug import sensitive_variables
from bera_control.services import issue_bootstrap


class Command(BaseCommand):
    help = 'Generate one DB-backed bootstrap token, valid for 10 minutes. Interactive Shell only, or --output-file.'

    def add_arguments(self, parser):
        parser.add_argument('--output-file', help='Create a NEW private file instead of printing the token.')

    @sensitive_variables('token')
    def handle(self, *args, **options):
        output_file = options.get('output_file')
        if not output_file and not self.stdout.isatty():
            raise CommandError('Token se ne ispisuje u build/logove. Koristite interaktivni Render Shell '
                               'ili --output-file /sigurna/putanja/token.txt.')
        handle = None
        try:
            if output_file:
                # Exclusive creation; never overwrite or follow an existing symlink.
                handle = os.fdopen(os.open(Path(output_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w')
            token = issue_bootstrap()
            if handle:
                handle.write(token + '\n')
                handle.flush()
                self.stdout.write('Token je spremljen u privatni fajl. Otvorite /bera-control/setup/ u roku 10 minuta.')
            else:
                self.stdout.write('Otvorite /bera-control/setup/. Token unesite u polje tokena; odaberite novu lozinku. Vrijedi 10 minuta:')
                self.stdout.write(token)
        except PermissionDenied as exc:
            raise CommandError(str(exc)) from None
        except OSError:
            raise CommandError('Nije moguće kreirati novi privatni fajl za token.') from None
        finally:
            if handle:
                handle.close()
