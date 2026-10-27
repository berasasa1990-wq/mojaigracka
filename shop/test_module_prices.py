from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from bera_control.models import ModulePrice


class PanelModulePricesTests(TestCase):
    def test_panel_displays_control_monthly_price(self):
        self.client.force_login(get_user_model().objects.create_user('price-manager', is_staff=True))
        ModulePrice.objects.create(code='premium_seo', monthly_price='29.50', purchase_price='200')
        response = self.client.get(reverse('panel_section', args=['moduli']))
        self.assertEqual(response.status_code, 200)
        module = next(module for module in response.context['bera_modules'] if module['code'] == 'premium_seo')
        self.assertEqual(str(module['monthly_price']), '29.50')
        self.assertContains(response, 'KM/mj')
        self.assertContains(response, 'Mjesečno korištenje')
        ModulePrice.objects.filter(code='premium_seo').update(monthly_price='35')
        response = self.client.get(reverse('panel_section', args=['moduli']))
        module = next(module for module in response.context['bera_modules'] if module['code'] == 'premium_seo')
        self.assertEqual(module['monthly_price'], 35)
