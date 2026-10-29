from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .cart import priced_items
from .models import CustomSetOffer, Product, Order


class CustomSetTests(TestCase):
    def setUp(self):
        self.offer = CustomSetOffer.objects.create(name='Izaberi tri', quantity=3, percent=20)
        self.products = [Product.objects.create(name=f'Artikal {i}', price=10) for i in range(4)]

    def total(self, count):
        quantities = {str(p.pk): 1 for p in self.products[:count]}
        return sum(i['subtotal'] for i in priced_items(self.products, quantities))

    def test_threshold_and_leftover(self):
        self.assertEqual(self.total(2), Decimal('20'))
        self.assertEqual(self.total(3), Decimal('24'))
        self.assertEqual(self.total(4), Decimal('34'))
        self.offer.is_active = False
        self.offer.save()
        self.assertEqual(self.total(3), Decimal('30'))

    def test_repeated_units_and_best_rule(self):
        CustomSetOffer.objects.create(name='Bolji set', quantity=3, percent=30)
        items = priced_items(self.products[:1], {str(self.products[0].pk): 6})
        self.assertEqual(items[0]['subtotal'], Decimal('42'))
        self.assertIn('30%', items[0]['custom_set_label'])

    def test_panel_save_and_checkout_labels(self):
        staff = get_user_model().objects.create_user('set-manager', is_staff=True)
        self.client.force_login(staff)
        url = reverse('panel_section', args=['akcije'])
        self.assertContains(self.client.get(url), 'Kreiraj svoj set')
        response = self.client.post(url, {'action': 'custom_set', 'offer_id': self.offer.pk, 'set-name': 'Tri poklona', 'set-quantity': 3, 'set-percent': 20, 'set-is_active': 'on'})
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        session['cart'] = {str(p.pk): 1 for p in self.products[:3]}
        session.save()
        self.assertContains(self.client.get(reverse('cart')), 'Tri poklona')
        self.client.post(reverse('checkout'), {'customer_name': 'Kupac', 'email': 'a@example.com', 'phone': '061123456', 'address': 'Ulica 1', 'city': 'Sarajevo', 'postal_code': '71000'})
        order = Order.objects.get()
        self.assertEqual(sum(i.unit_price * i.quantity for i in order.items.all()), Decimal('24'))
        self.assertTrue(all('20%' in i.promotion for i in order.items.all()))

    def test_delete_action_requires_staff_and_updates_cart_pricing(self):
        url = reverse('panel_section', args=['akcije'])
        self.client.post(url, {'action': 'delete_custom_set', 'offer_id': self.offer.pk})
        self.assertTrue(CustomSetOffer.objects.filter(pk=self.offer.pk).exists())
        staff = get_user_model().objects.create_user('delete-set-manager', is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(url), 'Obriši akciju')
        self.assertRedirects(self.client.post(url, {'action': 'delete_custom_set', 'offer_id': self.offer.pk}), url)
        self.assertFalse(CustomSetOffer.objects.filter(pk=self.offer.pk).exists())
        self.assertEqual(self.total(3), Decimal('30'))
