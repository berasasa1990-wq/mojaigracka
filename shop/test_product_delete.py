from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Order, OrderItem, Product


class PanelProductDeleteTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='Test artikal', price='10.00')
        self.staff = get_user_model().objects.create_user('delete-manager', is_staff=True)
        self.url = reverse('panel_product_delete', args=[self.product.pk])

    def test_requires_staff_post_and_csrf(self):
        self.assertEqual(self.client.post(self.url).status_code, 302)
        customer = get_user_model().objects.create_user('delete-customer')
        self.client.force_login(customer)
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post(self.url).status_code, 403)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_panel_button_and_delete(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('panel_section', args=['artikli'])), self.url)
        self.assertRedirects(self.client.post(self.url), reverse('panel_section', args=['artikli']))
        self.assertFalse(Product.objects.filter(pk=self.product.pk).exists())

    def test_order_history_is_preserved(self):
        order = Order.objects.create()
        item = OrderItem.objects.create(order=order, product=self.product, quantity=1, unit_price='10.00')
        self.client.force_login(self.staff)
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, 'Artikal se ne može obrisati')
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
        self.assertTrue(OrderItem.objects.filter(pk=item.pk).exists())
