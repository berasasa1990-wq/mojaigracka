from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import Product


class ProductSkuTests(TestCase):
    def test_staff_can_save_sku_and_only_detail_displays_it(self):
        product = Product.objects.create(name='Figura', price='10.00')
        staff = get_user_model().objects.create_user('sku-manager', is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(reverse('panel_edit', args=['artikli', product.pk]), {
            'name': 'Figura', 'sku': 'FIG-001-XYZ', 'price': '10.00',
            'stock': 0, 'is_active': 'on',
        })
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.sku, 'FIG-001-XYZ')
        self.assertContains(self.client.get(product.get_absolute_url()), 'FIG-001-XYZ')
        self.assertNotContains(self.client.get(reverse('home')), 'FIG-001-XYZ')

    def test_old_product_uses_id_when_sku_is_empty(self):
        product = Product.objects.create(name='Bez šifre', price='10.00')
        self.assertContains(self.client.get(product.get_absolute_url()), f'<dd>{product.pk}</dd>', html=True)
