from django.contrib.auth import get_user_model
from django.test import TestCase
from .forms import CustomerLoginForm, PanelLoginForm


class EmailLoginTests(TestCase):
    def test_duplicate_email_with_distinct_passwords(self):
        users = get_user_model()
        first = users.objects.create_user('first', email='buyer@example.com', password='first-password')
        users.objects.create_user('second', email='buyer@example.com', password='second-password')
        form = CustomerLoginForm(data={'username': 'BUYER@example.com', 'password': 'first-password'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user(), first)
        self.assertFalse(CustomerLoginForm(data={'username': 'buyer@example.com', 'password': 'wrong'}).is_valid())

    def test_ambiguous_credentials_are_rejected(self):
        for name in ('first', 'second'):
            get_user_model().objects.create_user(name, email='same@example.com', password='same-password')
        self.assertFalse(CustomerLoginForm(data={'username': 'same@example.com', 'password': 'same-password'}).is_valid())

    def test_panel_accepts_email_and_keeps_staff_requirement(self):
        user = get_user_model().objects.create_user('manager', email='staff@example.com', password='test-pass', is_staff=True)
        form = PanelLoginForm(data={'username': user.email, 'password': 'test-pass'})
        self.assertTrue(form.is_valid(), form.errors)
        user.is_staff = False
        user.save()
        self.assertFalse(PanelLoginForm(data={'username': user.email, 'password': 'test-pass'}).is_valid())

    def test_customer_can_use_username_when_email_is_ambiguous(self):
        user = get_user_model().objects.create_user('unique-buyer', email='same@example.com', password='same-pass')
        get_user_model().objects.create_user('other-buyer', email='same@example.com', password='same-pass')
        form = CustomerLoginForm(data={'username': 'unique-buyer', 'password': 'same-pass'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user(), user)
