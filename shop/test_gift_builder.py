from django.test import TestCase
from django.urls import reverse
from .models import Product, Order


class GiftBuilderTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='Rođendanski poklon', price=10)

    def test_catalog_and_search(self):
        Product.objects.create(name='Skriven', price=1, is_active=False)
        response = self.client.get(reverse('gift_catalog'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['products']), 1)
        self.assertEqual(response.json()['products'][0]['add_url'], reverse('cart_update', args=[self.product.pk]))
        self.assertEqual(self.client.get(reverse('gift_catalog'), {'q': 'nepostojeci'}).json()['products'], [])

    def test_packaging_is_saved_with_order(self):
        response = self.client.post(reverse('cart_update', args=[self.product.pk]), {'action': 'add', 'quantity': 2, 'gift_packaging': 'celofan'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['gift_packaging'], 'celofan')
        self.assertEqual(self.client.session['cart'][str(self.product.pk)], 2)
        self.client.post(reverse('checkout'), {'customer_name': 'Kupac', 'email': 'buyer@example.com', 'phone': '061123456', 'address': 'Ulica 1', 'city': 'Sarajevo', 'postal_code': '71000'})
        self.assertIn('Celofansko pakovanje', Order.objects.get().note)
        self.assertNotIn('gift_packaging', self.client.session)

    def test_free_wrap_requires_confirmation_and_is_saved_in_order(self):
        self.assertEqual(self.client.get(reverse('gift_wrap')).status_code, 405)
        self.assertNotIn('gift_packaging', self.client.session)
        self.client.post(reverse('gift_wrap'), {'action': 'confirm'})
        self.client.post(reverse('cart_update', args=[self.product.pk]), {'quantity': 1})
        self.assertContains(self.client.get(reverse('cart')), 'Pakovanje u foliju ukrasnu')
        self.client.post(reverse('checkout'), {'customer_name': 'Kupac', 'email': 'a@example.com', 'phone': '061123456', 'address': 'Ulica 1', 'city': 'Sarajevo', 'postal_code': '71000'})
        order = Order.objects.get()
        self.assertIn('Pakovanje u foliju ukrasnu — BESPLATNO', order.note)
        self.assertEqual(sum(i.unit_price * i.quantity for i in order.items.all()), self.product.price)

    def test_wrap_can_be_removed(self):
        self.client.post(reverse('gift_wrap'), {'action': 'confirm'})
        self.client.post(reverse('gift_wrap'), {'action': 'remove'})
        self.assertNotIn('gift_packaging', self.client.session)

    def test_header_opens_matching_wrap_dialog(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'aria-controls="giftWrapDialog"')
        self.assertContains(response, 'id="giftWrapDialog"')
        self.assertNotContains(response, 'id="giftBuilder"')
        self.assertContains(response, reverse('gift_wrap'))

    def test_wrap_confirmation_returns_to_shopping(self):
        response = self.client.post(reverse('gift_wrap'), {'action': 'confirm'})
        self.assertRedirects(response, reverse('home'))
        self.assertEqual(self.client.session['gift_packaging'], 'folija')
