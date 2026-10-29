import json
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings, RequestFactory
from django.urls import reverse
from .models import Product, Order, MetaTrackingEvent
from .meta_pixel import capi_payload, send_capi, purchase_event


@override_settings(META_PIXEL_ID='1761995418366231', META_CAPI_ENABLED=False, META_CAPI_ACCESS_TOKEN='', META_CONSENT_CHECK='', META_CONSENT_COOKIE='')
class MetaPixelTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='Pixel product', price=Decimal('20.00'))

    def config(self, response):
        from re import search
        match = search(r'<script id="meta-pixel-config" type="application/json">(.*?)</script>', response.content.decode())
        return json.loads(match.group(1)) if match else None

    def add(self, quantity=1):
        return self.client.post(reverse('cart_update', args=[self.product.pk]), {'action': 'add', 'quantity': quantity}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def checkout(self):
        return self.client.post(reverse('checkout'), {'customer_name': 'Test Buyer', 'email': 'buyer@example.com', 'phone': '061123456', 'address': 'Ulica 1', 'city': 'Sarajevo', 'postal_code': '71000'})

    def test_pageview_and_product_content(self):
        config = self.config(self.client.get(reverse('home')))
        self.assertEqual(config['pixel_id'], '1761995418366231')
        self.assertEqual([e['name'] for e in config['events']], ['PageView'])
        response = self.client.get(self.product.get_absolute_url())
        self.assertEqual(response.content.count(b'id="meta-pixel-config"'), 1)
        view = next(e for e in self.config(response)['events'] if e['name'] == 'ViewContent')
        self.assertEqual(view['data']['currency'], 'BAM')
        self.assertEqual(view['data']['value'], 20)
        self.assertEqual(view['data']['content_ids'], [str(self.product.pk)])
        self.assertEqual(view['data']['contents'][0]['quantity'], 1)

    def test_add_only_on_success_and_real_quantity(self):
        response = self.add(2)
        event = response.json()['meta_event']
        self.assertEqual(event['name'], 'AddToCart')
        self.assertEqual(event['data']['value'], 40)
        self.assertEqual(event['data']['quantity'], 2)
        self.assertEqual(self.add(-10).status_code, 400)
        self.assertEqual(MetaTrackingEvent.objects.filter(name='AddToCart').count(), 1)
        self.client.post(reverse('cart_update', args=[self.product.pk]), {'quantity': 0})
        self.assertEqual(MetaTrackingEvent.objects.filter(name='AddToCart').count(), 1)

    def test_non_ajax_add_is_delivered_once_after_redirect(self):
        response = self.client.post(reverse('cart_update', args=[self.product.pk]), {'action': 'add', 'quantity': 1}, follow=True)
        self.assertIn('AddToCart', [e['name'] for e in self.config(response)['events']])
        self.assertNotIn('AddToCart', [e['name'] for e in self.config(self.client.get(reverse('cart')))['events']])

    def test_checkout_purchase_exact_order_value_no_refresh_repeat(self):
        self.add(2)
        checkout = self.client.get(reverse('checkout'))
        start = next(e for e in self.config(checkout)['events'] if e['name'] == 'InitiateCheckout')
        self.assertEqual(start['data']['value'], float(checkout.context['grand_total']))
        self.assertEqual(self.checkout().status_code, 302)
        order = Order.objects.get()
        event = MetaTrackingEvent.objects.get(name='Purchase')
        self.assertEqual(event.order, order)
        self.assertEqual(event.data['value'], float(order.total))
        success = reverse('checkout') + '?success=1'
        first = self.config(self.client.get(success))['events']
        second = self.config(self.client.get(success))['events']
        self.assertEqual(sum(e['name'] == 'Purchase' for e in first), 1)
        self.assertEqual(sum(e['name'] == 'Purchase' for e in second), 0)
        pixel_event = next(e for e in first if e['name'] == 'Purchase')
        self.assertEqual(pixel_event['event_id'], capi_payload(event)['event_id'])
        self.assertEqual(pixel_event['data']['currency'], 'BAM')
        self.assertNotIn('InitiateCheckout', [e['name'] for e in first])

    def test_invalid_checkout_never_creates_purchase(self):
        self.add()
        self.client.post(reverse('checkout'), {})
        self.assertFalse(MetaTrackingEvent.objects.filter(name='Purchase').exists())

    @override_settings(META_PIXEL_ID='')
    def test_missing_id_disables_everything(self):
        self.assertIsNone(self.config(self.client.get('/')))
        self.add()
        self.assertFalse(MetaTrackingEvent.objects.exists())

    @override_settings(META_CONSENT_COOKIE='marketing', META_CONSENT_GRANTED_VALUE='yes')
    def test_consent_gate(self):
        self.assertIsNone(self.config(self.client.get('/')))
        self.assertFalse(MetaTrackingEvent.objects.exists())
        self.client.cookies['marketing'] = 'no'
        self.assertIsNone(self.config(self.client.get('/')))
        self.client.cookies['marketing'] = 'yes'
        self.assertIsNotNone(self.config(self.client.get('/')))

    def test_capi_disabled_without_token(self):
        self.client.get('/')
        event = MetaTrackingEvent.objects.first()
        with patch('shop.meta_pixel.urlopen') as network:
            self.assertFalse(send_capi(event))
            with override_settings(META_CAPI_ENABLED=True):
                self.assertFalse(send_capi(event))
            network.assert_not_called()
        with self.assertRaises(CommandError):
            call_command('send_meta_events')

    def test_capi_payload_and_token_remain_server_side(self):
        response = self.client.get(self.product.get_absolute_url())
        event = MetaTrackingEvent.objects.get(name='ViewContent')
        with override_settings(META_CAPI_ENABLED=True, META_CAPI_ACCESS_TOKEN='private-test-token', META_CAPI_API_VERSION='v26.0'):
            with patch('shop.meta_pixel.urlopen') as network:
                network.return_value.__enter__.return_value.read.return_value = b'{"events_received":1}'
                self.assertTrue(send_capi(event))
                request = network.call_args.args[0]
                payload = json.loads(request.data)
                self.assertEqual(payload['data'][0]['event_id'], str(event.event_id))
                self.assertNotIn('private-test-token', request.full_url)
        self.assertNotIn(b'private-test-token', response.content)

    def test_cards_require_payment_confirmation(self):
        order = Order.objects.create(total=10)
        request = RequestFactory().get('/')
        request.session = self.client.session
        self.assertIsNone(purchase_event(request, order, payment_method='card'))
        self.assertFalse(MetaTrackingEvent.objects.filter(name='Purchase').exists())
        event = purchase_event(request, order, payment_method='card', payment_confirmed=True)
        self.assertIsNotNone(event)
        self.assertEqual(purchase_event(request, order, payment_method='card', payment_confirmed=True).pk, event.pk)

    def test_staff_excluded(self):
        user = get_user_model().objects.create_user('meta-manager', is_staff=True)
        self.client.force_login(user)
        self.assertIsNone(self.config(self.client.get('/')))

    def test_bundle_add_tracks_all_members_and_discounted_value(self):
        from bera_control.services import issue_module_code, display_activation_code, redeem_module_code
        activation = issue_module_code('bundle')
        redeem_module_code('bundle', display_activation_code(activation))
        self.product.sale_type = 'bundle'
        self.product.bundle_percent = 20
        self.product.save()
        second = Product.objects.create(name='Bundle second', price=30)
        self.product.bundle_products.set([second])
        response = self.client.post(reverse('cart_add_bundle', args=[self.product.pk]), {}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        event = response.json()['meta_event']
        self.assertEqual(event['data']['value'], 40)
        self.assertEqual(event['data']['quantity'], 2)
        self.assertEqual(set(event['data']['content_ids']), {str(self.product.pk), str(second.pk)})

    def test_quantity_update_uses_actual_added_units(self):
        self.add(2)
        response = self.client.post(reverse('cart_update', args=[self.product.pk]), {'quantity': 5}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        data = response.json()['meta_event']['data']
        self.assertEqual(data['value'], 60)
        self.assertEqual(data['contents'], [{'id': str(self.product.pk), 'quantity': 3, 'item_price': 20.0}])

    def test_manually_opened_success_page_does_not_invent_purchase(self):
        self.add()
        response = self.client.get(reverse('checkout') + '?success=1')
        self.assertNotIn('Purchase', [e['name'] for e in self.config(response)['events']])
        self.assertFalse(MetaTrackingEvent.objects.filter(name='Purchase').exists())
