from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from shop.models import Order, OrderItem, Product


class OrderPrintTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('printer', is_staff=True)
        self.order = Order.objects.create(customer_name='Kupac Test', address='Ulica 1',
            city='Sarajevo', delivery_price=5, loyalty_discount=2, total=33)
        product = Product.objects.create(name='Test artikal', price=15)
        OrderItem.objects.create(order=self.order, product=product, quantity=2, unit_price=15)
        self.url = reverse('wms:order_print', args=[self.order.pk])

    def test_staff_print_uses_order_prices_and_keeps_status(self):
        self.client.force_login(self.staff)
        with patch('wms.views.require_module'):
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['subtotal'], Decimal('30'))
            self.assertEqual(response.context['items'][0].line_total, Decimal('30'))
            for text in ['Kupac Test', 'Test artikal', 'Ulica 1', 'window.print()', 'Ukupno za plaćanje']:
                self.assertContains(response, text)
            listing = self.client.get(reverse('wms:orders'))
            self.assertContains(listing, reverse('wms:orders_bulk_print'))
            self.assertNotContains(listing, self.url)
            self.assertNotContains(listing, 'Označi kao zapakovano')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'placed')
        self.assertIn('no-store', response['Cache-Control'])

    def test_permissions_and_drafts(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.staff)
        with patch('wms.views.require_module'):
            self.order.status = 'draft'
            self.order.save()
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_bulk_print_and_confirmation_are_separate(self):
        self.client.force_login(self.staff)
        second = Order.objects.create(customer_name='Drugi kupac', total=10)
        bulk = reverse('wms:orders_bulk_print')
        mark = reverse('wms:orders_mark_printed')
        ids = [str(self.order.pk), str(second.pk)]
        with patch('wms.views.require_module'):
            response = self.client.get(bulk, {'orders': ids})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.context['documents']), 2)
            self.assertContains(response, 'Označi kao odštampano')
            self.order.refresh_from_db()
            self.assertIsNone(self.order.printed_at)
            self.assertEqual(self.client.get(mark).status_code, 405)
            self.assertEqual(self.client.post(mark, {'orders': ids}).status_code, 302)
            self.order.refresh_from_db()
            second.refresh_from_db()
            self.assertIsNotNone(self.order.printed_at)
            self.assertIsNotNone(second.printed_at)
            original = self.order.printed_at
            self.client.post(mark, {'orders': ids})
            self.order.refresh_from_db()
            self.assertEqual(self.order.printed_at, original)
            self.assertEqual(self.order.status, 'placed')
            self.assertContains(self.client.get(reverse('wms:orders')), 'Odštampano')

    def test_bulk_rejects_empty_invalid_and_draft_selection(self):
        self.client.force_login(self.staff)
        bulk = reverse('wms:orders_bulk_print')
        with patch('wms.views.require_module'):
            for ids in [[], ['wrong'], ['999999999'], [str(self.order.pk)] * 101]:
                self.assertEqual(self.client.get(bulk, {'orders': ids}).status_code, 400)
            self.order.status = 'draft'
            self.order.save()
            self.assertEqual(self.client.get(bulk, {'orders': [self.order.pk]}).status_code, 400)
            self.assertEqual(self.client.post(reverse('wms:orders_mark_printed'), {'orders': [self.order.pk]}).status_code, 400)

    def test_order_search_by_name_phone_number_and_status(self):
        self.client.force_login(self.staff)
        self.order.phone = '061123456'
        self.order.save(update_fields=['phone'])
        other = Order.objects.create(customer_name='Drugi kupac', status='shipped')
        with patch('wms.views.require_module'):
            for query in ['Kupac Test', '061123', f'#{self.order.pk}']:
                response = self.client.get(reverse('wms:orders'), {'q': query})
                self.assertEqual(list(response.context['orders']), [self.order])
            response = self.client.get(reverse('wms:orders'), {'q': 'Drugi', 'status': 'sve'})
            self.assertEqual(list(response.context['orders']), [other])
            response = self.client.get(reverse('wms:orders'), {'q': 'nema rezultata'})
            self.assertEqual(list(response.context['orders']), [])
