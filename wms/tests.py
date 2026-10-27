from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from bera_control.models import ModuleActivation
from bera_control.services import display_activation_code, initialize, issue_bootstrap
from bera_licensing.services import module_enabled


@override_settings(BERA_LICENSE_INSTALLATION_ID='', BERA_LICENSE_API_CREDENTIAL='')
class WmsActivationTests(TestCase):
    def test_owner_activation_and_disable_control_wms_access(self):
        password = 'River!Stone-Control-7294'
        initialize(issue_bootstrap(), password)
        self.client.post(reverse('bera_control:login'), {'password': password})
        response = self.client.get(reverse('bera_control:dashboard'))
        module = next(item for item in response.context['modules'] if item['code'] == 'wms')
        self.assertTrue(module['connected'])
        response = self.client.post(reverse('bera_control:generate_code', args=['wms']))
        self.assertEqual(response.status_code, 302)
        code = display_activation_code(ModuleActivation.objects.get(module='wms'))
        staff = get_user_model().objects.create_user('wms-manager', is_staff=True)
        self.client.force_login(staff)
        self.assertFalse(module_enabled('wms'))
        self.assertEqual(self.client.get(reverse('wms:dashboard')).status_code, 403)
        self.client.post(reverse('bera_module_code_activate'), {
            'module': 'wms', 'activation_code': code,
        })
        self.assertTrue(module_enabled('wms'))
        self.assertEqual(self.client.get(reverse('wms:dashboard')).status_code, 200)
        self.client.post(reverse('bera_control:toggle', args=['wms']), {'enabled': 'off'})
        self.assertFalse(module_enabled('wms'))
        self.assertEqual(self.client.get(reverse('wms:dashboard')).status_code, 403)


class WarehouseArticleTests(TestCase):
    def test_orders_keep_wms_navigation_for_list_preview_and_packing(self):
        from unittest.mock import patch
        from shop.models import Order
        staff = get_user_model().objects.create_user('warehouse-orders', is_staff=True)
        self.client.force_login(staff)
        order = Order.objects.create(customer_name='WMS kupac', status='placed')
        url = reverse('wms:orders')
        with patch('wms.views.require_module'):
            response = self.client.get(url)
            self.assertTemplateUsed(response, 'wms/base.html')
            self.assertContains(response, 'WMS kupac')
            self.assertContains(response, 'aria-label="WMS opcije"')
            self.assertEqual(response.context['section'], 'orders')
            preview = self.client.get(url, {'preview': order.pk})
            self.assertTemplateUsed(preview, 'shop/partials/panel_order_preview.html')
            response = self.client.post(url, {'order_id': order.pk, 'action': 'pack'})
            self.assertRedirects(response, url)
            order.refresh_from_db()
            self.assertEqual(order.status, 'shipped')

    def test_history_tracks_stock_changes_and_manual_reason(self):
        from shop.models import Product
        from .models import Location, StockMovement
        product = Product.objects.create(name='Istorija artikla', price=10, stock=5)
        location = Location.objects.create(name='Polica istorije')
        url = reverse('wms:product_location', args=[product.pk])
        self.client.post(url, {'location': location.pk, 'quantity': 8})
        added = StockMovement.objects.first()
        self.assertEqual((added.change, added.stock_before, added.stock_after), (3, 5, 8))
        self.client.post(url, {'location': location.pk, 'quantity': 6, 'reason': 'Otpis oštećene robe'})
        removed = StockMovement.objects.first()
        self.assertEqual((removed.change, removed.stock_before, removed.stock_after), (-2, 8, 6))
        self.assertEqual(removed.reason, 'Otpis oštećene robe')
        count = StockMovement.objects.count()
        self.client.post(url, {'location': location.pk, 'quantity': 6})
        self.assertEqual(StockMovement.objects.count(), count)
        response = self.client.get(reverse('wms:history'))
        self.assertContains(response, 'wms-stock-added')
        self.assertContains(response, 'wms-stock-removed')
        self.assertContains(response, 'Otpis oštećene robe')
        self.assertNotContains(self.client.get(reverse('wms:history'), {'q': 'nepostojeći'}), 'Istorija artikla')

    def setUp(self):
        self.staff = get_user_model().objects.create_user('warehouse-staff', is_staff=True)
        self.client.force_login(self.staff)
        from unittest.mock import patch
        self.module_patch = patch('wms.views.require_module')
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def test_assign_location_and_search_existing_article(self):
        from shop.models import Product
        product = Product.objects.create(name='Postojeći artikal', price='10', stock=4)
        from .models import Location
        location = Location.objects.create(name='Regal B12')
        self.client.post(reverse('wms:product_location', args=[product.pk]), {'location': location.pk, 'quantity': 4})
        self.assertEqual(product.warehouse_location.location, location)
        response = self.client.get(reverse('wms:dashboard'), {'q': 'B12'})
        self.assertContains(response, 'Postojeći artikal')
        self.assertEqual(response.context['stock_total'], 4)
        self.assertNotContains(self.client.get(reverse('wms:dashboard'), {'q': 'Nepostojeći'}), 'Postojeći artikal')

    def test_customer_cannot_create_or_assign_locations(self):
        self.staff.is_staff = False
        self.staff.save(update_fields=['is_staff'])
        self.assertEqual(self.client.post(reverse('wms:product_location', args=[1]), {}).status_code, 302)

    def test_locations_groups_stock_and_removes_article_entry(self):
        from shop.models import Product
        from .models import Location, ProductLocation
        location = Location.objects.create(name='Regal A1')
        for name, stock in [('Prvi', 3), ('Drugi', 5)]:
            product = Product.objects.create(name=name, price=10, stock=stock)
            ProductLocation.objects.create(product=product, location=location, quantity=stock)
        response = self.client.get(reverse('wms:locations'))
        self.assertContains(response, 'Regal A1')
        row = response.context['page_obj'][0]
        self.assertEqual(row.stock_total, 8)
        self.assertEqual(row.product_count, 2)
        self.assertNotContains(response, 'Unos artikla')
        self.assertNotContains(self.client.get(reverse('wms:dashboard')), 'Unos artikla')
        self.assertEqual(self.client.get('/wms/artikli/unos/').status_code, 404)

    def test_only_existing_locations_can_be_assigned(self):
        from shop.models import Product
        from .models import ProductLocation
        product = Product.objects.create(name='Artikal', price=10)
        url = reverse('wms:product_location', args=[product.pk])
        response = self.client.post(url, {'location': 'Nova slobodna lokacija'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('location', response.context['form'].errors)
        self.assertFalse(ProductLocation.objects.filter(product=product).exists())
        response = self.client.post(url, {'location': 999999})
        self.assertIn('location', response.context['form'].errors)

    def test_create_location_before_assigning_it(self):
        from .models import Location
        response = self.client.post(reverse('wms:locations'), {'name': 'Regal C1'})
        self.assertRedirects(response, reverse('wms:locations'))
        location = Location.objects.get(name='Regal C1')
        response = self.client.get(reverse('wms:locations'))
        self.assertContains(response, location.name)
        self.assertEqual(response.context['page_obj'][0].stock_total, 0)
        response = self.client.post(reverse('wms:locations'), {'name': 'Regal C1'})
        self.assertIn('name', response.context['form'].errors)
        self.assertEqual(Location.objects.count(), 1)

    def test_location_quantity_validation_and_save(self):
        from shop.models import Product
        from .models import Location, ProductLocation
        product = Product.objects.create(name='Količina', price=10, stock=0, is_out_of_stock=True)
        location = Location.objects.create(name='Polica 4')
        url = reverse('wms:product_location', args=[product.pk])
        for quantity in [-1]:
            response = self.client.post(url, {'location': location.pk, 'quantity': quantity})
            self.assertIn('quantity', response.context['form'].errors)
        response = self.client.post(url, {'location': '', 'quantity': 3})
        self.assertIn('location', response.context['form'].errors)
        self.assertFalse(ProductLocation.objects.filter(product=product).exists())
        self.assertRedirects(self.client.post(url, {'location': location.pk, 'quantity': 150}), reverse('wms:dashboard'))
        self.assertEqual(ProductLocation.objects.get(product=product).quantity, 150)
        product.refresh_from_db()
        self.assertEqual(product.stock, 150)
        self.assertFalse(product.is_out_of_stock)
        response = self.client.get(reverse('wms:dashboard'))
        self.assertEqual(response.context['stock_total'], 150)
        self.assertContains(response, '<strong>150</strong> kom.', html=True)
        self.assertNotContains(response, 'kom. na lokaciji')
        response = self.client.get(reverse('wms:locations'))
        self.assertEqual(response.context['page_obj'][0].stock_total, 150)
        self.assertRedirects(self.client.post(url, {'location': location.pk, 'quantity': 0}), reverse('wms:dashboard'))
        product.refresh_from_db()
        self.assertEqual(product.stock, 0)
        self.assertTrue(product.is_out_of_stock)
        self.assertEqual(ProductLocation.objects.get(product=product).quantity, 0)
