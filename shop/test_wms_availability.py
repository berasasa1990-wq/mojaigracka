from unittest.mock import patch
from django.test import Client, TestCase
from django.urls import reverse
from shop.models import Product


class WmsAvailabilityTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='WMS artikal', price=20, stock=0)
        self.data = {'customer_name': 'Test Kupac', 'email': 'test@example.com',
                     'phone': '061123456', 'address': 'Test ulica 1', 'city': 'Sarajevo', 'postal_code': '71000'}

    def wms(self, enabled):
        from bera_licensing.services import module_enabled
        return patch('bera_licensing.services.module_enabled', side_effect=lambda code: enabled if code == 'wms' else module_enabled(code))

    def test_availability_follows_module_and_preserves_manual_flag(self):
        for enabled in [False, True]:
            with self.wms(enabled):
                for stock in [0, 3]:
                    for manual in [False, True]:
                        self.product.stock = stock
                        self.product.is_out_of_stock = manual
                        self.assertEqual(self.product.is_available, stock > 0 if enabled else True)

    def test_disabled_wms_ignores_quantity_and_does_not_decrement_stock(self):
        with self.wms(False):
            response = self.client.post(reverse('cart_update', args=[self.product.pk]), {'quantity': 5})
            self.assertEqual(response.status_code, 302)
            self.assertContains(self.client.get(self.product.get_absolute_url()), 'Na stanju')
            self.assertEqual(self.client.get(reverse('cart')).context['cart_count'], 5)
            self.assertEqual(self.client.post(reverse('checkout'), self.data).status_code, 302)
            self.product.refresh_from_db()
            self.assertEqual(self.product.stock, 0)
            self.assertFalse(self.product.is_out_of_stock)

    def test_disabled_wms_ignores_old_out_of_stock_flag_and_hides_stock_controls(self):
        from shop.forms import ProductForm
        self.product.is_out_of_stock = True
        self.product.save(update_fields=['is_out_of_stock'])
        with self.wms(False):
            self.assertTrue(self.product.is_available)
            self.assertEqual(self.product.cart_quantity_limit, 99)
            self.assertContains(self.client.get(self.product.get_absolute_url()), 'Na stanju')
            self.assertEqual(self.client.post(reverse('cart_update', args=[self.product.pk]),
                                              {'quantity': 2}).status_code, 302)
            form = ProductForm(instance=self.product)
            self.assertNotIn('stock', form.fields)
            self.assertNotIn('is_out_of_stock', form.fields)
        with self.wms(True):
            self.assertFalse(self.product.is_available)
            self.assertIn('stock', ProductForm(instance=self.product).fields)

    def test_enabled_wms_zero_stock_blocks_cart_and_positive_stock_overrides_manual_flag(self):
        with self.wms(True):
            url = reverse('cart_update', args=[self.product.pk])
            self.assertEqual(self.client.post(url, {'quantity': 1}).status_code, 400)

            self.product.stock = 2
            self.product.is_out_of_stock = True
            self.product.save()
            self.assertEqual(self.client.post(url, {'quantity': 3}).status_code, 400)
            self.assertEqual(self.client.post(url, {'quantity': 2}).status_code, 302)
            self.assertEqual(self.client.post(reverse('checkout'), self.data).status_code, 302)
            self.product.refresh_from_db()
            self.assertEqual(self.product.stock, 0)
            self.assertFalse(self.product.is_available)
            movement = self.product.stock_movements.first()
            self.assertEqual(movement.change, -2)
            self.assertIn('Narudžba #', movement.reason)
            self.assertEqual(self.client.post(url, {'quantity': 1}).status_code, 400)

    def test_enabled_wms_allows_exact_stock_above_99_and_rejects_excess(self):
        self.product.stock = 150
        self.product.save(update_fields=['stock'])
        with self.wms(True):
            url = reverse('cart_update', args=[self.product.pk])
            self.assertEqual(self.client.post(url, {'quantity': 151}).status_code, 400)
            self.assertEqual(self.client.post(url, {'quantity': 150}).status_code, 302)
            self.assertContains(self.client.get(reverse('cart')), 'max="150"')
            self.assertEqual(self.client.post(url, {'action': 'add', 'quantity': 1}).status_code, 400)
            self.assertEqual(self.client.post(reverse('checkout'), self.data).status_code, 302)
            self.product.refresh_from_db()
            self.assertEqual(self.product.stock, 0)

    def test_checkout_rejects_quantity_when_stock_has_decreased(self):
        self.product.stock = 3
        self.product.save(update_fields=['stock'])
        with self.wms(True):
            self.client.post(reverse('cart_update', args=[self.product.pk]), {'quantity': 3})
            self.product.stock = 2
            self.product.save(update_fields=['stock'])
            response = self.client.post(reverse('checkout'), self.data)
            self.assertContains(response, 'Dostupnost artikala je promijenjena')
            self.assertFalse(self.product.order_items.exists())

    def test_unavailable_cart_item_is_removed_before_restock(self):
        session = self.client.session
        session['cart'] = {str(self.product.pk): 1}
        session.save()
        with self.wms(True):
            self.assertEqual(self.client.get(reverse('cart')).context['cart_count'], 0)
            self.assertEqual(self.client.session['cart'], {})
            self.product.stock = 1
            self.product.save(update_fields=['stock'])
            response = self.client.post(reverse('cart_update', args=[self.product.pk]),
                                        {'action': 'add', 'quantity': 1})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.session['cart'], {str(self.product.pk): 1})

    def test_last_unit_already_in_cart_has_clear_message(self):
        self.product.stock = 1
        self.product.save(update_fields=['stock'])
        with self.wms(True):
            url = reverse('cart_update', args=[self.product.pk])
            self.client.post(url, {'action': 'add', 'quantity': 1})
            response = self.client.post(url, {'action': 'add', 'quantity': 1})
            self.assertEqual(response.status_code, 400)
            self.assertIn('U korpi već imate', response.json()['error'])
            self.assertEqual(self.client.session['cart'], {str(self.product.pk): 1})

    def test_carts_do_not_reserve_last_unit_and_first_order_consumes_it(self):
        self.product.stock = 1
        self.product.save(update_fields=['stock'])
        other_customer = Client()
        url = reverse('cart_update', args=[self.product.pk])
        with self.wms(True):
            for customer in (self.client, other_customer):
                response = customer.post(url, {'action': 'add', 'quantity': 1})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(customer.session['cart'], {str(self.product.pk): 1})
            self.product.refresh_from_db()
            self.assertEqual(self.product.stock, 1)
            self.assertTrue(self.product.is_available)
            self.assertFalse(self.product.order_items.exists())

            response = other_customer.post(reverse('checkout'), self.data)
            self.assertRedirects(response, reverse('checkout') + '?success=1')
            self.product.refresh_from_db()
            self.assertEqual(self.product.stock, 0)
            self.assertFalse(self.product.is_available)
            self.assertEqual(self.product.order_items.count(), 1)
            self.assertEqual(self.client.post(url, {'action': 'add', 'quantity': 1}).status_code, 400)

            self.client.post(reverse('checkout'), self.data)
            self.assertEqual(self.product.order_items.count(), 1)
            self.product.refresh_from_db()
            self.assertEqual(self.product.stock, 0)
            self.assertEqual(self.client.get(reverse('cart')).context['cart_count'], 0)
