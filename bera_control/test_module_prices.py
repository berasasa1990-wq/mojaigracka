from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from .models import ModulePrice
from .tests import ControlTests


class ModulePriceTests(TestCase):
    initialize = ControlTests.initialize
    login = ControlTests.login

    def test_owner_saves_prices_and_totals_only_active_modules(self):
        self.initialize()
        self.login()
        url = reverse('bera_control:set_price', args=['premium_seo'])
        self.assertEqual(self.client.post(url, {'purchase_price': '150.50', 'monthly_price': '20.25'}).status_code, 302)
        self.assertEqual(ModulePrice.objects.get(code='premium_seo').monthly_price, Decimal('20.25'))
        ModulePrice.objects.create(code='bonus_reward', purchase_price=100, monthly_price=10)
        with patch('bera_control.views.module_enabled', side_effect=lambda code: code == 'premium_seo'):
            response = self.client.get(reverse('bera_control:dashboard'))
            self.assertEqual(response.context['total_purchase'], Decimal('150.50'))
            self.assertEqual(response.context['total_monthly'], Decimal('20.25'))
            self.assertContains(response, 'modulePriceDialog')
        with patch('bera_control.views.module_enabled', return_value=False):
            response = self.client.get(reverse('bera_control:dashboard'))
            self.assertEqual(response.context['total_monthly'], 0)

    def test_invalid_prices_and_unauthorized_access(self):
        url = reverse('bera_control:set_price', args=['premium_seo'])
        self.assertEqual(self.client.post(url, {'purchase_price': 10, 'monthly_price': 5}).status_code, 302)
        self.assertFalse(ModulePrice.objects.exists())
        self.initialize()
        self.login()
        self.assertEqual(self.client.get(url).status_code, 405)
        for value in ['-1', '12.345', 'invalid', 'NaN']:
            self.client.post(url, {'purchase_price': value, 'monthly_price': 10})
        self.assertFalse(ModulePrice.objects.exists())
        self.assertEqual(self.client.post(reverse('bera_control:set_price', args=['unknown']), {'purchase_price': 0, 'monthly_price': 0}).status_code, 404)

    def test_global_monthly_rebate_preserves_base_prices_and_purchase(self):
        self.initialize()
        self.login()
        ModulePrice.objects.create(code='premium_seo', purchase_price=200, monthly_price=30)
        url = reverse('bera_control:set_monthly_rebate')
        self.assertEqual(self.client.post(url, {'monthly_rebate': '15'}).status_code, 302)
        with patch('bera_control.views.module_enabled', side_effect=lambda code: code == 'premium_seo'):
            response = self.client.get(reverse('bera_control:dashboard'))
            self.assertEqual(response.context['total_monthly'], Decimal('25.50'))
            self.assertEqual(response.context['total_purchase'], 200)
        self.assertEqual(ModulePrice.objects.get(code='premium_seo').monthly_price, 30)
        self.client.post(url, {'monthly_rebate': '15'})
        from .pricing import monthly_rebate, discounted_monthly
        self.assertEqual(discounted_monthly(30, monthly_rebate()), Decimal('25.50'))
        for invalid in ['-1', '101', 'invalid']:
            self.client.post(url, {'monthly_rebate': invalid})
            self.assertEqual(monthly_rebate(), 15)
        self.client.post(url, {'monthly_rebate': '0'})
        self.assertEqual(discounted_monthly(30, monthly_rebate()), 30)
