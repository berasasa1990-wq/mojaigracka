import hashlib
import io
import json
from datetime import timedelta
from urllib.error import HTTPError, URLError
from unittest.mock import patch
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings, RequestFactory
from django.urls import reverse
from django.utils import timezone
from .models import Product, Order, OrderItem, MetaTrackingEvent
from .meta_pixel import create_event, purchase_event, send_capi, capi_payload, collect_user_data


@override_settings(META_PIXEL_ID='1761995418366231', META_CAPI_ENABLED=True,
                   META_CAPI_ACCESS_TOKEN='private-fixture-token', META_CAPI_API_VERSION='v26.0',
                   META_CONSENT_CHECK='', META_CONSENT_COOKIE='', META_SEND_HASHED_PII=False,
                   META_CAPI_MAX_ATTEMPTS=3, META_CAPI_RETRY_SECONDS=1, META_TRUSTED_PROXY_HOPS=0)
class MetaCapiTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='CAPI Product', price=25)
        self.request = RequestFactory().get('/artikal/1/', HTTP_USER_AGENT='Test browser', REMOTE_ADDR='8.8.8.8')
        self.request.session = self.client.session

    def event(self):
        return create_event(self.request, 'ViewContent', {'currency': 'BAM', 'value': 25})

    def accepted(self, network):
        network.return_value.__enter__.return_value.read.return_value = b'{"events_received":1}'

    def order_event(self):
        order = Order.objects.create(total=25, email=' Buyer@Example.COM ', phone='061 123 456')
        OrderItem.objects.create(order=order, product=self.product, unit_price=25, quantity=1)
        return order, purchase_event(self.request, order)

    def test_ip_agent_cookies_click_id_and_no_raw_contact_data(self):
        self.request.COOKIES = {'_fbp': 'fb.1.100.browser', '_fbc': 'fb.1.100.click'}
        data = collect_user_data(self.request)
        self.assertEqual(data['client_ip_address'], '8.8.8.8')
        self.assertEqual(data['client_user_agent'], 'Test browser')
        self.assertEqual(data['fbp'], 'fb.1.100.browser')
        self.assertEqual(data['fbc'], 'fb.1.100.click')
        self.request.COOKIES = {}
        self.request.GET = {'fbclid': 'click-from-ad'}
        self.assertTrue(collect_user_data(self.request)['fbc'].endswith('.click-from-ad'))
        self.assertNotIn('em', data)
        self.assertNotIn('ph', data)
        self.request.META['HTTP_X_FORWARDED_FOR'] = '1.1.1.1'
        self.assertEqual(collect_user_data(self.request)['client_ip_address'], '8.8.8.8')
        with override_settings(META_TRUSTED_PROXY_HOPS=1):
            self.assertEqual(collect_user_data(self.request)['client_ip_address'], '1.1.1.1')

    @override_settings(META_SEND_HASHED_PII=True, META_CONSENT_COOKIE='marketing', META_CONSENT_GRANTED_VALUE='yes')
    def test_email_phone_hashing_requires_explicit_permission(self):
        order = Order.objects.create(total=25, email=' Buyer@Example.COM ', phone='061 123 456')
        self.assertNotIn('em', collect_user_data(self.request, order))
        self.request.COOKIES['marketing'] = 'yes'
        data = collect_user_data(self.request, order)
        self.assertEqual(data['em'], [hashlib.sha256(b'buyer@example.com').hexdigest()])
        self.assertEqual(data['ph'], [hashlib.sha256(b'38761123456').hexdigest()])
        self.assertNotIn('buyer@example.com', json.dumps(data))
        self.assertNotIn('061 123 456', json.dumps(data))
        with override_settings(META_CONSENT_COOKIE=''):
            self.assertNotIn('em', collect_user_data(self.request, order))

    def test_success_is_idempotent_and_uses_same_uuid(self):
        event = self.event()
        with patch('shop.meta_pixel.urlopen') as network:
            self.accepted(network)
            self.assertTrue(send_capi(event))
            self.assertFalse(send_capi(event))
            network.assert_called_once()
            request = network.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(payload['data'][0]['event_id'], str(event.event_id))
            self.assertEqual(payload['data'][0]['action_source'], 'website')
            self.assertEqual(network.call_args.kwargs['timeout'], 5)
            self.assertNotIn(settings.META_CAPI_ACCESS_TOKEN, request.full_url)
        event.refresh_from_db()
        self.assertEqual(event.capi_status, 'sent')
        self.assertEqual(event.capi_attempts, 1)

    def test_transient_network_error_backoff_and_retry(self):
        event = self.event()
        with patch('shop.meta_pixel.urlopen', side_effect=URLError('secret URL must not be logged')):
            self.assertFalse(send_capi(event))
        event.refresh_from_db()
        self.assertEqual(event.capi_status, 'pending')
        self.assertEqual(event.capi_last_error, 'network_timeout')
        self.assertGreater(event.capi_next_attempt_at, timezone.now())
        first_id = str(event.event_id)
        with patch('shop.meta_pixel.urlopen') as network:
            self.assertFalse(send_capi(event))
            network.assert_not_called()
            MetaTrackingEvent.objects.filter(pk=event.pk).update(capi_next_attempt_at=timezone.now() - timedelta(seconds=1))
            self.accepted(network)
            self.assertTrue(send_capi(event))
            self.assertEqual(json.loads(network.call_args.args[0].data)['data'][0]['event_id'], first_id)

    def test_permanent_error_safe_storage_and_no_retry(self):
        event = self.event()
        error = HTTPError('https://graph.facebook.com/?access_token=private-fixture-token', 400, 'bad', {}, io.BytesIO(b'{"error":{"code":190}}'))
        with patch('shop.meta_pixel.urlopen', side_effect=error):
            self.assertFalse(send_capi(event))
        event.refresh_from_db()
        self.assertEqual(event.capi_status, 'failed')
        self.assertEqual(event.capi_last_error, 'http_400')
        self.assertNotIn('private-fixture-token', event.capi_last_error)
        with patch('shop.meta_pixel.urlopen') as network:
            self.assertFalse(send_capi(event))
            network.assert_not_called()

    def test_active_lease_blocks_second_worker_and_stale_lease_recovers(self):
        event = self.event()
        MetaTrackingEvent.objects.filter(pk=event.pk).update(capi_status='processing', capi_locked_until=timezone.now() + timedelta(minutes=1))
        with patch('shop.meta_pixel.urlopen') as network:
            self.assertFalse(send_capi(event))
            network.assert_not_called()
            MetaTrackingEvent.objects.filter(pk=event.pk).update(capi_locked_until=timezone.now() - timedelta(seconds=1))
            self.accepted(network)
            self.assertTrue(send_capi(event))

    def test_cancelled_purchase_is_not_sent_or_rendered(self):
        order, event = self.order_event()
        order.status = 'cancelled'
        order.save()
        with patch('shop.meta_pixel.urlopen') as network:
            self.assertFalse(send_capi(event))
            network.assert_not_called()
        event.refresh_from_db()
        self.assertEqual(event.capi_status, 'skipped')
        self.assertEqual(event.capi_last_error, 'order_not_eligible')
        self.assertIsNone(purchase_event(self.request, order))
        session = self.client.session
        session['last_order'] = order.pk
        session.save()
        self.client.get(reverse('checkout') + '?success=1')
        event.refresh_from_db()
        self.assertIsNone(event.browser_claimed_at)

    def test_cod_duplicate_and_card_payment_boundary(self):
        order, cod = self.order_event()
        self.assertEqual(purchase_event(self.request, order).pk, cod.pk)
        card_order = Order.objects.create(total=25)
        OrderItem.objects.create(order=card_order, product=self.product, unit_price=25, quantity=1)
        self.assertIsNone(purchase_event(self.request, card_order, payment_method='card'))
        confirmed = purchase_event(self.request, card_order, payment_method='card', payment_confirmed=True)
        self.assertEqual(confirmed.pk, purchase_event(self.request, card_order, payment_method='card', payment_confirmed=True).pk)
        with patch('shop.meta_pixel.urlopen') as network:
            self.accepted(network)
            self.assertTrue(send_capi(confirmed))
            self.assertFalse(send_capi(confirmed))
            network.assert_called_once()

    def test_http_failure_rolls_back_order_without_purchase(self):
        self.client.post(reverse('cart_update', args=[self.product.pk]), {'quantity': 1})
        with patch('shop.views.OrderItem.objects.create', side_effect=RuntimeError('order storage failed')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('checkout'), {'customer_name': 'Buyer', 'email': 'a@example.com', 'phone': '061123456', 'address': 'Ulica 1', 'city': 'Sarajevo', 'postal_code': '71000'})
        self.assertFalse(Order.objects.exists())
        self.assertFalse(MetaTrackingEvent.objects.filter(name='Purchase').exists())

    def test_web_requests_never_perform_capi_network_calls(self):
        with patch('shop.meta_pixel.urlopen') as network:
            self.client.get(self.product.get_absolute_url())
            self.client.post(reverse('cart_update', args=[self.product.pk]), {'action': 'add', 'quantity': 2}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.client.get(reverse('checkout'))
            self.client.post(reverse('checkout'), {'customer_name': 'Buyer', 'email': 'a@example.com', 'phone': '061123456', 'address': 'Ulica 1', 'city': 'Sarajevo', 'postal_code': '71000'})
            network.assert_not_called()
        self.assertTrue(MetaTrackingEvent.objects.filter(name='Purchase', capi_status='pending').exists())

    def test_command_dispatches_queue_not_pageview(self):
        self.client.get(self.product.get_absolute_url())
        with patch('shop.meta_pixel.urlopen') as network:
            self.accepted(network)
            call_command('send_meta_events', stdout=io.StringIO())
            self.assertEqual(network.call_count, 1)
            self.assertEqual(json.loads(network.call_args.args[0].data)['data'][0]['event_name'], 'ViewContent')

    @override_settings(META_CONSENT_COOKIE='marketing', META_CONSENT_GRANTED_VALUE='yes')
    def test_revoke_blocks_queued_server_events(self):
        self.client.cookies['marketing'] = 'yes'
        self.client.get(self.product.get_absolute_url())
        event = MetaTrackingEvent.objects.get(name='ViewContent')
        self.client.cookies['marketing'] = 'no'
        self.client.get('/')
        event.refresh_from_db()
        self.assertEqual(event.capi_status, 'skipped')
        with patch('shop.meta_pixel.urlopen') as network:
            self.assertFalse(send_capi(event))
            network.assert_not_called()

    def test_retry_stops_at_attempt_limit(self):
        event = self.event()
        with patch('shop.meta_pixel.urlopen', side_effect=TimeoutError()):
            for attempt in range(3):
                MetaTrackingEvent.objects.filter(pk=event.pk).update(capi_next_attempt_at=timezone.now() - timedelta(seconds=1))
                self.assertFalse(send_capi(event))
        event.refresh_from_db()
        self.assertEqual(event.capi_attempts, 3)
        self.assertEqual(event.capi_status, 'failed')

    def test_optional_retry_failed_keeps_original_id(self):
        event = self.event()
        MetaTrackingEvent.objects.filter(pk=event.pk).update(capi_status='failed', capi_attempts=3)
        with patch('shop.meta_pixel.urlopen') as network:
            self.accepted(network)
            call_command('send_meta_events', retry_failed=True, stdout=io.StringIO())
            self.assertEqual(json.loads(network.call_args.args[0].data)['data'][0]['event_id'], str(event.event_id))

    def test_expired_event_is_not_replayed(self):
        event = self.event()
        MetaTrackingEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(hours=25))
        with patch('shop.meta_pixel.urlopen') as network:
            self.assertFalse(send_capi(event))
            network.assert_not_called()
        event.refresh_from_db()
        self.assertEqual(event.capi_last_error, 'expired')

    def test_source_url_uses_same_origin_referrer_without_private_query(self):
        request = RequestFactory().post('/korpa/1/', HTTP_REFERER='http://testserver/artikal/1/?email=private@example.com')
        request.session = self.client.session
        event = create_event(request, 'AddToCart', {'value': 25, 'currency': 'BAM'})
        self.assertEqual(capi_payload(event)['event_source_url'], 'http://testserver/artikal/1/')
        request.META['HTTP_REFERER'] = 'https://external.example/private'
        other = create_event(request, 'AddToCart')
        self.assertEqual(other.source_url, 'http://testserver/korpa/1/')

    def test_malformed_referrer_cannot_break_event_creation(self):
        request = RequestFactory().post('/checkout/', HTTP_REFERER='http://[')
        request.session = self.client.session
        self.assertIsNotNone(create_event(request, 'InitiateCheckout'))

    @override_settings(META_CONSENT_CHECK='nonexistent_module.consent')
    def test_broken_consent_hook_fails_closed(self):
        self.assertIsNone(create_event(self.request, 'ViewContent'))
