import hashlib
from datetime import timedelta
from io import StringIO
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.core.management import call_command, CommandError
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.utils import timezone

from .models import ControlState, AuditEvent
from .services import initialize, issue_bootstrap

PASSWORD = 'Bootstrap-Flow!Secure-7294'


class BootstrapFlowTests(TestCase):
    def test_uninitialized_login_redirects_without_counting_token_as_bad_password(self):
        token = issue_bootstrap()
        self.assertRedirects(self.client.get('/bera-control/'), '/bera-control/setup/')
        self.assertEqual(self.client.post('/bera-control/', {'password': token}).status_code, 302)
        self.assertEqual(ControlState.objects.get(pk=1).failures, 0)
        self.assertFalse(AuditEvent.objects.filter(action='login_failed').exists())
        self.assertContains(self.client.get('/bera-control/setup/'), 'Token vrijedi 10 minuta i nije lozinka')

    def test_valid_token_is_hashed_consumed_and_works_for_another_client(self):
        now = timezone.now()
        with patch('bera_control.services.timezone.now', return_value=now):
            token = issue_bootstrap()
        state = ControlState.objects.get(pk=1)
        self.assertEqual(state.bootstrap_digest, hashlib.sha256(token.encode()).hexdigest())
        self.assertEqual(state.bootstrap_expires, now + timedelta(minutes=10))
        self.assertNotEqual(state.bootstrap_digest, token)
        client = Client()
        response = client.post('/bera-control/setup/', {'token': token, 'password': PASSWORD, 'confirm': PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertContains(client.get('/bera-control/'), 'Lozinka je postavljena.')
        state.refresh_from_db()
        self.assertEqual(state.bootstrap_digest, '')
        self.assertIsNone(state.bootstrap_expires)
        with self.assertRaises(PermissionDenied):
            initialize(token, PASSWORD)
        self.assertEqual(client.get('/bera-control/setup/').status_code, 404)
        self.assertEqual(AuditEvent.objects.filter(action='initialized').count(), 1)

    def test_wrong_token_does_not_consume_valid_token(self):
        token = issue_bootstrap()
        response = self.client.post('/bera-control/setup/', {'token': 'invalid-token',
                                   'password': PASSWORD, 'confirm': PASSWORD})
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, token, status_code=403)
        self.assertTrue(ControlState.objects.get(pk=1).bootstrap_digest)
        initialize(token, PASSWORD)

    @override_settings(TIME_ZONE='Europe/Sarajevo')
    def test_exact_expiry_boundary_and_timezone(self):
        now = timezone.now()
        with patch('bera_control.services.timezone.now', return_value=now):
            token = issue_bootstrap()
        with patch('bera_control.services.timezone.now', return_value=now + timedelta(minutes=10)):
            with self.assertRaises(PermissionDenied):
                initialize(token, PASSWORD)
        self.assertIsNone(ControlState.objects.get(pk=1).initialized_at)
        with patch('bera_control.services.timezone.now', return_value=now + timedelta(minutes=10, seconds=1)):
            with self.assertRaises(PermissionDenied):
                initialize(token, PASSWORD)

    def test_token_works_just_before_expiry_and_ignores_outer_copy_whitespace(self):
        now = timezone.now()
        with patch('bera_control.services.timezone.now', return_value=now):
            token = issue_bootstrap()
        with patch('bera_control.services.timezone.now', return_value=now + timedelta(minutes=9, seconds=59)):
            initialize('  ' + token + '\n', PASSWORD)
        self.assertIsNotNone(ControlState.objects.get(pk=1).initialized_at)

    def test_command_does_not_print_tokens_to_noninteractive_logs(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command('bera_control_bootstrap', stdout=out)
        self.assertFalse(ControlState.objects.get(pk=1).bootstrap_digest)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'token'
            call_command('bera_control_bootstrap', output_file=str(path), stdout=out)
            token = path.read_text().strip()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(token, out.getvalue())
            with self.assertRaises(CommandError):
                call_command('bera_control_bootstrap', output_file=str(path), stdout=out)
            self.assertEqual(path.read_text().strip(), token)


class BootstrapProcessTests(SimpleTestCase):
    def test_issue_and_consume_from_separate_processes_and_different_secrets(self):
        script = '''
import os,sys
from pathlib import Path
from django.conf import settings
settings.configure(INSTALLED_APPS=['bera_control'], USE_TZ=True,
                   TIME_ZONE='Asia/Tokyo' if sys.argv[3]=='consume' else 'UTC',
                   SECRET_KEY='process-specific-'+sys.argv[3],
                   DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': sys.argv[1]}})
import django
django.setup()
from django.db import connection
from bera_control.models import ControlState, AuditEvent
from bera_control.services import initialize
if sys.argv[3]=='issue':
    from django.core.management import call_command
    with connection.schema_editor() as editor:
        editor.create_model(ControlState)
        editor.create_model(AuditEvent)
    ControlState.objects.create(pk=1)
    from io import StringIO
    call_command('bera_control_bootstrap', output_file=sys.argv[2], stdout=StringIO())
else:
    initialize(Path(sys.argv[2]).read_text().strip(), 'Bootstrap-Process!7294')
    state=ControlState.objects.get(pk=1)
    assert state.initialized_at and not state.bootstrap_digest and state.bootstrap_expires is None
print('ok')
'''
        with TemporaryDirectory() as directory:
            for phase in ('issue', 'consume'):
                result = subprocess.run([sys.executable, '-c', script, str(Path(directory) / 'db.sqlite3'),
                                         str(Path(directory) / 'token'), phase],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'ok')
