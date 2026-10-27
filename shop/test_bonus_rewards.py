from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Product, Order, OrderItem, BonusRewardOffer, BonusRewardClaim, StoreSettings


class BonusRewardTests(TestCase):
    def setUp(self):
        self.module = patch('bera_licensing.services.module_enabled', side_effect=lambda code: code == 'bonus_reward')
        self.module.start()
        self.addCleanup(self.module.stop)
        self.product = Product.objects.create(name='Bonus telefon', price=100)
        self.offer = BonusRewardOffer.objects.create(product=self.product, percent=20)
        self.order = Order.objects.create(total=50, delivery_price=5, printed_at=timezone.now())
        session = self.client.session
        session['last_order'] = self.order.pk
        session.save()
        self.url = reverse('bonus_reward_add', args=[self.offer.pk])

    def show_offers(self):
        return self.client.get(reverse('checkout') + '?success=1')

    def test_popup_price_addition_and_no_duplicates(self):
        response = self.show_offers()
        self.assertContains(response, 'bonusRewardDialog')
        self.assertEqual(response.context['bonus_offers'][0].discounted_price, Decimal('80'))
        StoreSettings.objects.update_or_create(pk=1, defaults={'delivery_price': 5, 'free_delivery_threshold': 100})
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.total, Decimal('125'))
        self.assertEqual(self.order.delivery_price, 0)
        self.assertIsNone(self.order.printed_at)
        item = self.order.items.get()
        self.assertEqual(item.unit_price, 80)
        self.assertEqual(item.quantity, 1)
        self.client.post(self.url)
        self.assertEqual(self.order.items.count(), 1)
        self.assertEqual(BonusRewardClaim.objects.count(), 1)

    def test_session_offer_order_status_and_module_required(self):
        self.assertEqual(self.client.post(self.url).status_code, 400)
        self.show_offers()
        self.order.status = 'shipped'
        self.order.save()
        self.assertEqual(self.client.post(self.url).status_code, 400)
        with patch('bera_licensing.services.module_enabled', return_value=False):
            self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertEqual(OrderItem.objects.count(), 0)

    def test_unavailable_product_and_expired_order(self):
        self.show_offers()
        self.product.is_active = False
        self.product.save()
        self.assertEqual(self.client.post(self.url).status_code, 409)
        from datetime import timedelta
        Order.objects.filter(pk=self.order.pk).update(created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(self.show_offers().context['bonus_offers'], [])

    def test_max_four_offers_and_wms_decrement(self):
        for number in range(5):
            product = Product.objects.create(name=f'Ponuda {number}', price=10)
            BonusRewardOffer.objects.create(product=product, percent=10)
        self.assertEqual(len(self.show_offers().context['bonus_offers']), 4)
        self.product.stock = 1
        self.product.save()
        with patch('bera_licensing.services.module_enabled', return_value=True):
            self.assertEqual(self.client.post(self.url).status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)

    def test_panel_can_save_offer(self):
        staff = get_user_model().objects.create_user('bonus-manager', is_staff=True)
        self.client.force_login(staff)
        product = Product.objects.create(name='Drugi artikal', price=20)
        url = reverse('panel_section', args=['bonus-nagrada'])
        self.assertEqual(self.client.post(url, {'product': product.pk, 'percent': 15, 'is_active': 'on'}).status_code, 302)
        self.assertTrue(BonusRewardOffer.objects.filter(product=product, percent=15).exists())
