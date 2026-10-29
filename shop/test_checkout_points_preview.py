from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import LoyaltyCard, LoyaltyRules, SiteModule, Product, StoreSettings, Order


class CheckoutPointsPreviewTests(TestCase):
    def setUp(self):
        SiteModule.objects.update_or_create(code='loyalty', defaults={'enabled': True})
        self.user = get_user_model().objects.create_user('preview-buyer')
        self.card, _ = LoyaltyCard.objects.get_or_create(customer=self.user)
        self.card.points = 1000
        self.card.save()
        LoyaltyRules.objects.create(redemption_points=100, point_value=5, max_discount_percent=50)
        StoreSettings.objects.create(pk=1, delivery_price=10, free_delivery_threshold=100)
        self.product = Product.objects.create(name='Preview', price=100)
        self.client.force_login(self.user)
        session = self.client.session
        session['cart'] = {str(self.product.pk): 1}
        session.save()
        self.url = reverse('checkout')

    def preview(self, points):
        return self.client.get(self.url, {'points_preview': '1', 'points': points})

    def test_preview_discount_total_and_delivery_match_final_order(self):
        response = self.preview(100)
        data = response.json()
        self.assertEqual(Decimal(data['points_discount']), Decimal('5'))
        self.assertEqual(Decimal(data['delivery_price']), Decimal('10'))
        self.assertEqual(Decimal(data['grand_total']), Decimal('105'))
        self.assertEqual(self.preview(0).json()['grand_total'], '100.00')
        self.assertIn('no-store', response['Cache-Control'])
        self.card.refresh_from_db()
        self.assertEqual(self.card.points, 1000)
        self.assertFalse(Order.objects.exists())
        self.client.post(reverse('cart'), {'loyalty_points': 100})
        self.client.post(self.url, dict(customer_name='Kupac', email='buyer@example.com', phone='061123456', address='Ulica 1', city='Sarajevo', postal_code='71000', note='Test', loyalty_points=100))
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal(data['grand_total']))
        self.assertEqual(order.loyalty_discount, Decimal('5'))

    def test_preview_clamps_to_balance_and_percentage_limit(self):
        data = self.preview(99999).json()
        self.assertEqual(data['points_used'], 1000)
        self.assertEqual(Decimal(data['points_discount']), Decimal('50'))
        self.assertEqual(Decimal(data['grand_total']), Decimal('60'))
        for points in [-100, 'invalid']:
            self.assertEqual(self.preview(points).json()['points_used'], 0)

    def test_disabled_points_and_guests_get_no_discount(self):
        LoyaltyRules.objects.filter(pk=1).update(points_enabled=False)
        self.assertEqual(self.preview(100).json()['points_used'], 0)
        self.client.logout()
        session = self.client.session
        session['cart'] = {str(self.product.pk): 1}
        session.save()
        self.assertEqual(self.preview(100).json()['points_used'], 0)

    def test_checkout_cannot_override_cart_selection(self):
        self.client.post(reverse('cart'), {'loyalty_points': 100})
        response = self.client.get(self.url)
        self.assertNotContains(response, 'name="loyalty_points"')
        self.assertEqual(response.context['points_used'], 100)
        self.client.post(self.url, dict(customer_name='Kupac', email='buyer@example.com', phone='061123456', address='Ulica 1', city='Sarajevo', postal_code='71000', loyalty_points=1000))
        self.assertEqual(Order.objects.get().loyalty_discount, Decimal('5'))
        self.assertNotIn('cart_loyalty_points', self.client.session)

    def test_cart_max_remove_and_render(self):
        self.client.post(reverse('cart'), {'use_max_points': '1'})
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.context['points_used'], 1000)
        self.assertContains(response, 'Iskoristi bodove')
        self.assertNotContains(response, 'name="loyalty_points"')
        self.client.post(reverse('cart'), {'loyalty_points': 0})
        self.assertEqual(self.client.get(self.url).context['points_used'], 0)

    def test_no_click_means_no_points_used(self):
        self.assertEqual(self.client.get(reverse('cart')).context['points_used'], 0)
        self.assertEqual(self.client.get(self.url).context['points_used'], 0)
        self.client.post(self.url, dict(customer_name='Kupac', email='buyer@example.com', phone='061123456', address='Ulica 1', city='Sarajevo', postal_code='71000', loyalty_points=1000))
        self.assertEqual(Order.objects.get().loyalty_discount, Decimal('0'))
        self.card.refresh_from_db()
        self.assertEqual(self.card.points, 1000)

    def test_empty_cart_clears_previous_loyalty_choices(self):
        session = self.client.session
        session['loyalty_customer'] = self.user.pk
        session['cart_loyalty_points'] = {'customer': self.user.pk, 'points': 1000}
        session['cart'] = {}
        session.save()
        self.client.get(reverse('cart'))
        self.assertNotIn('loyalty_customer', self.client.session)
        self.assertNotIn('cart_loyalty_points', self.client.session)

    def test_sale_items_excluded_from_points_and_popup(self):
        self.product.original_price = 120
        self.product.save()
        self.client.post(reverse('cart'), {'use_max_points': '1'})
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.context['points_used'], 0)
        self.assertContains(response, 'loyalty-notice')
        self.assertEqual(response.context['loyalty_eligible_total'], Decimal('0'))
        self.client.post(self.url, dict(customer_name='Kupac', email='buyer@example.com', phone='061123456', address='Ulica 1', city='Sarajevo', postal_code='71000'))
        self.assertEqual(Order.objects.get().loyalty_discount, Decimal('0'))
        self.card.refresh_from_db()
        self.assertEqual(self.card.points, 1000)

    def test_mixed_cart_points_only_apply_to_regular_items(self):
        self.product.original_price = 120
        self.product.save()
        regular = Product.objects.create(name='Redovna cijena', price=20)
        session = self.client.session
        session['cart'][str(regular.pk)] = 1
        session.save()
        self.client.post(reverse('cart'), {'use_max_points': '1'})
        response = self.client.get(self.url)
        self.assertEqual(response.context['points_discount'], Decimal('10'))
        self.assertEqual(response.context['loyalty_eligible_total'], Decimal('20'))
