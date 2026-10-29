from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import AnalyticsEvent, Product
from .analytics import dashboard


class AnalyticsTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='Analitika artikal', price=10)

    def test_ads_and_visits_are_deduplicated(self):
        self.client.get('/', {'utm_source': 'fb', 'utm_medium': 'paid_social'})
        self.client.get('/')
        self.assertEqual(AnalyticsEvent.objects.filter(kind='visit').count(), 1)
        event = AnalyticsEvent.objects.get(kind='visit')
        self.assertEqual(event.source, 'Facebook')
        self.assertTrue(event.paid)
        self.assertEqual(dashboard(30)['ad_visitors'], 1)

    def test_fbclid_alone_is_not_assumed_paid(self):
        self.client.get('/', {'fbclid': 'example'})
        self.assertFalse(AnalyticsEvent.objects.get(kind='visit').paid)

    def test_product_views_and_successful_cart_increases(self):
        self.client.get(self.product.get_absolute_url())
        self.client.get(self.product.get_absolute_url())
        self.client.post(reverse('cart_update', args=[self.product.pk]), {'action': 'add', 'quantity': 2})
        self.client.post(reverse('cart_update', args=[self.product.pk]), {'quantity': 1})
        self.client.post(reverse('cart_update', args=[self.product.pk]), {'quantity': -1})
        self.assertEqual(AnalyticsEvent.objects.filter(kind='view').count(), 2)
        self.assertEqual(AnalyticsEvent.objects.get(kind='cart').quantity, 2)
        self.assertEqual(dashboard(30)['cart_additions'][0]['count'], 2)

    def test_panel_is_private_and_staff_not_tracked(self):
        url = reverse('panel_section', args=['analitika'])
        self.assertEqual(self.client.get(url).status_code, 302)
        staff = get_user_model().objects.create_user('analytics-manager', is_staff=True)
        self.client.force_login(staff)
        self.client.get(self.product.get_absolute_url())
        self.assertFalse(AnalyticsEvent.objects.exists())
        self.assertContains(self.client.get(url), 'Odakle dolaze posjetioci?')
