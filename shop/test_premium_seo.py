from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import SEOSettings


class PremiumSeoPanelTests(TestCase):
    def test_locked_access_and_settings_moved(self):
        self.client.force_login(get_user_model().objects.create_user('premium-manager', is_staff=True))
        url = reverse('panel_section', args=['premium-seo'])
        with patch('bera_licensing.services.module_enabled', return_value=False):
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {'settings_section': 'meta_description', 'meta-description': 'Blocked'}).status_code, 403)
        with patch('bera_licensing.services.module_enabled', return_value=True):
            self.assertContains(self.client.get(url), 'Spremi meta opis')
            self.assertContains(self.client.get(url), 'SEO sajta i društvene mreže')
            self.assertNotContains(self.client.get(reverse('panel_section', args=['podesavanje'])), 'Spremi meta opis')
            self.assertContains(self.client.get(reverse('panel_section', args=['moduli'])), 'Uredi SEO postavke')
        self.assertEqual(self.client.post(reverse('panel_section', args=['podesavanje']), {'settings_section': 'meta_description', 'meta-description': 'Blocked'}).status_code, 400)
        self.assertFalse(SEOSettings.objects.filter(description='Blocked').exists())
