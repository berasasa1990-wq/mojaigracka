import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.hashers import check_password
from django.core.management import call_command, CommandError
from django.test import Client, TestCase

from .models import ControlState, AuditEvent

PASSWORD = 'Once-Only-Control!7294'


class InitialPasswordTests(TestCase):
    def run_setup(self, password=None):
        output = StringIO()
        with patch.dict(os.environ, {'BERA_CONTROL_INITIAL_PASSWORD': password or ''}):
            call_command('bera_control_initialize', stdout=output)
        return output.getvalue()

    def test_password_persists_without_environment_and_retries_do_not_reset_it(self):
        output = self.run_setup(PASSWORD)
        self.assertNotIn(PASSWORD, output)
        original = ControlState.objects.get(pk=1)
        self.assertTrue(check_password(PASSWORD, original.password_hash))
        self.assertNotEqual(PASSWORD, original.password_hash)
        self.run_setup('Another-Strong-Password!7294')
        self.run_setup()
        state = ControlState.objects.get(pk=1)
        self.assertEqual(state.password_hash, original.password_hash)
        self.assertEqual(state.initialized_at, original.initialized_at)
        self.assertEqual(state.generation, original.generation)
        self.assertEqual(AuditEvent.objects.filter(action='initialized').count(), 1)
        # Fresh browser session, no environment variable: login uses stored hash.
        client = Client()
        self.assertEqual(client.post('/bera-control/', {'password': PASSWORD}).status_code, 302)
        self.assertIn('bera_control', client.session)
        self.assertEqual(client.get('/bera-control/setup/').status_code, 404)

    def test_missing_or_weak_password_does_not_initialize(self):
        for password in (None, '123'):
            with self.assertRaises(CommandError):
                self.run_setup(password)
        state = ControlState.objects.get(pk=1)
        self.assertFalse(state.initialized_at)
        self.assertFalse(state.password_hash)
        self.assertFalse(AuditEvent.objects.filter(action='initialized').exists())

    def test_cannot_overwrite_preexisting_hash_even_with_missing_timestamp(self):
        ControlState.objects.filter(pk=1).update(password_hash='existing-protected-hash')
        with self.assertRaises(CommandError):
            self.run_setup(PASSWORD)
        self.assertEqual(ControlState.objects.get(pk=1).password_hash, 'existing-protected-hash')
