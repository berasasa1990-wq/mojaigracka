import os

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.views.decorators.debug import sensitive_variables

from bera_control.models import ControlState
from bera_control.services import initialize_password_once


class Command(BaseCommand):
    help = 'Set BERA Control password ONCE from BERA_CONTROL_INITIAL_PASSWORD; never reset existing access.'

    @sensitive_variables('password')
    def handle(self, *args, **options):
        if ControlState.objects.filter(pk=1, initialized_at__isnull=False).exists():
            self.stdout.write('BERA CONTROL je već postavljen. Postojeća lozinka ostaje nepromijenjena.')
            return
        password = os.environ.get('BERA_CONTROL_INITIAL_PASSWORD', '')
        if not password:
            raise CommandError('Postavite BERA_CONTROL_INITIAL_PASSWORD za prvo postavljanje.')
        try:
            initialized = initialize_password_once(password)
        except ValidationError:
            raise CommandError('Lozinka mora imati najmanje 12 znakova i zadovoljiti Django pravila jačine.') from None
        except PermissionDenied:
            raise CommandError('Postojeća lozinka nije promijenjena. Koristite postupak oporavka pristupa.') from None
        if initialized:
            self.stdout.write(self.style.SUCCESS('BERA CONTROL lozinka je trajno postavljena u bazi. '
                                                'Uklonite BERA_CONTROL_INITIAL_PASSWORD iz environmenta.'))
        else:
            self.stdout.write('BERA CONTROL je već postavljen. Postojeća lozinka ostaje nepromijenjena.')
