from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Product, StockNotification
from .stock_notifications import notify_available_product


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class StockNotificationTests(TestCase):
    def setUp(self):
        self.wms = patch('bera_licensing.services.module_enabled', return_value=False)
        self.wms.start()
        self.addCleanup(self.wms.stop)
        self.product = Product.objects.create(name='Telefon', price=100, is_out_of_stock=True)
        self.url = reverse('stock_notification_subscribe', args=[self.product.pk])

    def subscribe(self, email='kupac@example.com'):
        return self.client.post(self.url, {'email': email})

    def test_guest_validation_deduplication_and_button(self):
        self.assertEqual(self.subscribe('nije-email').status_code, 400)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.subscribe('Kupac@example.com').status_code, 200)
        self.assertEqual(self.subscribe().status_code, 200)
        self.assertEqual(StockNotification.objects.count(), 1)
        self.assertContains(self.client.get(self.product.get_absolute_url()), 'Obavijesti pri dolasku')

    def test_logged_in_customer_needs_only_click(self):
        user = get_user_model().objects.create_user('kupac', email='nalog@example.com')
        self.client.force_login(user)
        self.assertEqual(self.client.post(self.url).status_code, 200)
        self.assertEqual(StockNotification.objects.get().email, user.email)

    def test_manual_restock_sends_once_after_commit_and_can_resubscribe(self):
        self.subscribe()
        with self.captureOnCommitCallbacks(execute=True):
            self.product.is_out_of_stock = False
            self.product.save(update_fields=['is_out_of_stock'])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Telefon', mail.outbox[0].body)
        self.assertIn(self.product.get_absolute_url(), mail.outbox[0].body)
        notify_available_product(self.product.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.subscribe().status_code, 409)
        self.product.is_out_of_stock = True
        self.product.save()
        self.subscribe()
        self.assertIsNone(StockNotification.objects.get().notified_at)

    def test_wms_restock_and_inactive_product(self):
        self.subscribe()
        with patch('bera_licensing.services.module_enabled', return_value=True):
            with self.captureOnCommitCallbacks(execute=True):
                self.product.stock = 2
                self.product.save(update_fields=['stock'])
        self.assertEqual(len(mail.outbox), 1)
        self.product.is_active = False
        self.product.save()
        self.assertEqual(self.subscribe().status_code, 404)

    def test_delivery_failure_remains_pending_for_retry(self):
        self.subscribe()
        self.product.is_out_of_stock = False
        self.product.save()
        with patch('shop.stock_notifications.send_mail', side_effect=OSError('SMTP unavailable')):
            with self.assertLogs('shop.stock_notifications', level='ERROR'):
                notify_available_product(self.product.pk)
        self.assertIsNone(StockNotification.objects.get().notified_at)
        notify_available_product(self.product.pk)
        self.assertIsNotNone(StockNotification.objects.get().notified_at)
