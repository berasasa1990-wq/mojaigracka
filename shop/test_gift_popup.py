from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, GiftPopupSettings, Order, Product


class GiftPopupTests(TestCase):
    def setUp(self):
        self.a = Category.objects.create(name='Za dječake')
        self.b = Category.objects.create(name='Za djevojčice')
        self.config = GiftPopupSettings.objects.create(enabled=True, category=self.a, category_b=self.b,
                                                       percent=20, delay_seconds=3)
        self.products_a = [Product.objects.create(name=f'A {i}', price=100, category=self.a) for i in range(3)]
        self.products_b = [Product.objects.create(name=f'B {i}', price=50, category=self.b) for i in range(3)]
        self.answer_url = reverse('gift_popup_answer')
        self.select_url = reverse('gift_popup_select')

    def answer(self, answer='B', **extra):
        return self.client.post(self.answer_url, {'answer': answer, 'revision': str(self.config.revision), **extra})

    def claim(self):
        self.assertEqual(self.answer().status_code, 200)
        pk = self.client.session['gift_popup_offer']['products'][0]
        self.assertRedirects(self.client.post(self.select_url, {'product': pk}), reverse('cart'))
        return pk

    def test_config_home_only_and_panel_permissions(self):
        data = self.client.get(reverse('gift_popup_config')).json()
        self.assertEqual(data['delay'], 3)
        self.assertEqual(data['answer_b'], 'Djevojčicu')
        self.assertIn('no-store', self.client.get(reverse('gift_popup_config'))['Cache-Control'])
        self.assertContains(self.client.get(reverse('home')), 'id="giftPopup"')
        self.assertNotContains(self.client.get(reverse('sales')), 'id="giftPopup"')
        url = reverse('panel_section', args=['poklon-pop-up'])
        self.assertEqual(self.client.get(url).status_code, 302)
        user = get_user_model().objects.create_user('gift-manager', is_staff=True)
        self.client.force_login(user)
        self.assertContains(self.client.get(url), 'Kategorija za B')
        response = self.client.post(url, {'enabled': 'on', 'question': 'Za koga?', 'answer_a': 'A',
                                         'answer_b': 'B', 'category': self.a.pk, 'category_b': self.b.pk,
                                         'percent': 15, 'delay_seconds': 8})
        self.assertRedirects(response, url)
        self.config.refresh_from_db()
        self.assertEqual(self.config.percent, 15)
        self.assertEqual(self.config.delay_seconds, 8)

    def test_both_answers_draw_two_unique_products_from_correct_category(self):
        for answer, products in [('A', self.products_a), ('B', self.products_b)]:
            self.client = Client()
            response = self.answer(answer)
            self.assertEqual(response.status_code, 200)
            ids = self.client.session['gift_popup_offer']['products']
            self.assertEqual(len(set(ids)), 2)
            self.assertTrue(set(ids) <= {p.pk for p in products})
            self.assertIn('Kupi i obraduj', response.json()['html'])

    def test_draw_excludes_inactive_and_unavailable_and_handles_empty(self):
        Product.objects.filter(category=self.b).update(is_active=False)
        self.products_b[0].is_active = True
        self.products_b[0].save()
        Product.objects.create(name='Hidden', price=1, category=self.b, is_active=False)
        response = self.answer()
        self.assertEqual(self.client.session['gift_popup_offer']['products'], [self.products_b[0].pk])
        self.assertIn('40.00 KM', response.json()['html'])
        self.client = Client()
        Product.objects.filter(category=self.b).update(is_active=False)
        self.assertIn('trenutno nisu dostupna', self.answer().json()['html'])

    def test_disabled_wms_offers_products_even_with_old_out_of_stock_flag(self):
        Product.objects.filter(category=self.b).update(is_out_of_stock=True, stock=0)
        with patch('bera_licensing.services.module_enabled', return_value=False):
            self.assertEqual(self.answer().status_code, 200)
            self.assertEqual(len(self.client.session['gift_popup_offer']['products']), 2)

    def test_wms_draw_requires_stock(self):
        Product.objects.filter(category=self.b).update(stock=0)
        self.products_b[1].stock = 2
        self.products_b[1].save()
        with patch('bera_licensing.services.module_enabled', return_value=True):
            self.answer()
        self.assertEqual(self.client.session['gift_popup_offer']['products'], [self.products_b[1].pk])

    def test_repeated_answers_do_not_reroll_or_extend_offer(self):
        self.answer()
        first = self.client.session['gift_popup_offer']
        self.answer('A')
        self.assertEqual(first, self.client.session['gift_popup_offer'])

    def test_cannot_forge_discount_product_or_claim_without_answer(self):
        self.assertEqual(self.client.post(self.select_url, {'product': self.products_a[0].pk}).status_code, 400)
        self.assertEqual(self.answer('C').status_code, 400)
        self.assertEqual(self.answer(revision='bad').status_code, 400)
        self.answer(percent=100, price=0)
        self.assertEqual(self.client.post(self.select_url, {'product': self.products_a[0].pk}).status_code, 400)
        pk = self.client.session['gift_popup_offer']['products'][0]
        self.client.post(self.select_url, {'product': pk, 'percent': 100, 'price': 0})
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.context['cart_total'], Decimal('40.00'))

    def test_one_discounted_unit_only_and_checkout_matches_cart(self):
        pk = self.claim()
        self.client.post(reverse('cart_update', args=[pk]), {'quantity': 3})
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.context['cart_total'], Decimal('140.00'))
        self.assertContains(response, 'Poklon pop up')
        self.client.post(reverse('checkout'), dict(customer_name='Kupac', email='gift@example.com',
                         phone='061123456', address='Ulica 1', city='Sarajevo', postal_code='71000', note=''))
        order = Order.objects.get()
        items = list(order.items.all())
        self.assertEqual(sum(i.unit_price * i.quantity for i in items), Decimal('140.00'))
        self.assertEqual(sum(i.quantity for i in items if i.unit_price == 40), 1)
        self.assertTrue(any('Poklon pop up' in i.promotion for i in items))
        self.assertNotIn('gift_popup_offer', self.client.session)

    def test_selection_is_idempotent_and_cannot_switch_to_second_product(self):
        pk = self.claim()
        self.assertEqual(self.client.post(self.select_url, {'product': pk}).status_code, 302)
        self.assertEqual(self.client.session['cart'][str(pk)], 1)
        other = next(i for i in self.client.session['gift_popup_offer']['products'] if i != pk)
        self.assertEqual(self.client.post(self.select_url, {'product': other}).status_code, 400)

    def test_expired_disabled_or_changed_campaign_has_no_discount(self):
        pk = self.claim()
        session = self.client.session
        offer = session['gift_popup_offer']
        session['gift_popup_offer'] = {**offer, 'expires': 0}
        session.save()
        self.assertEqual(self.client.get(reverse('cart')).context['cart_total'], Decimal('50.00'))
        self.assertEqual(self.client.post(self.select_url, {'product': pk}).status_code, 400)
        self.config.enabled = False
        self.config.save()
        self.assertFalse(self.client.get(reverse('gift_popup_config')).json()['enabled'])
        self.assertEqual(self.client.get(reverse('cart')).context['cart_total'], Decimal('50.00'))

    def test_unavailable_or_moved_product_cannot_be_selected(self):
        self.answer()
        pk = self.client.session['gift_popup_offer']['products'][0]
        Product.objects.filter(pk=pk).update(category=self.a)
        self.assertEqual(self.client.post(self.select_url, {'product': pk}).status_code, 400)

    def test_better_existing_quantity_promotion_is_preserved(self):
        pk = self.claim()
        Product.objects.filter(pk=pk).update(sale_type='quantity', quantity_percent_2=50,
                                            quantity_percent_3=50, quantity_percent_over_3=50)
        self.client.post(reverse('cart_update', args=[pk]), {'quantity': 3})
        with patch('bera_licensing.services.module_enabled', side_effect=lambda code: code == 'quantity'):
            response = self.client.get(reverse('cart'))
        self.assertEqual(response.context['cart_total'], Decimal('75.00'))
        self.assertFalse(response.context['cart_items'][0].get('gift_applied'))

    def test_campaign_change_revokes_unexpired_claim(self):
        self.claim()
        old_revision = str(self.config.revision)
        self.config.percent = 30
        self.config.save()
        self.assertEqual(self.client.get(reverse('cart')).context['cart_total'], Decimal('50.00'))
        self.assertEqual(self.answer(revision=old_revision).status_code, 400)
        self.config.refresh_from_db()
        self.assertEqual(self.answer().status_code, 200)

    def test_disabled_campaign_revokes_unexpired_claim(self):
        self.claim()
        self.config.enabled = False
        self.config.save()
        self.assertEqual(self.client.get(reverse('cart')).context['cart_total'], Decimal('50.00'))
        self.assertEqual(self.answer().status_code, 400)

    def test_csrf_and_post_are_required(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(self.answer_url).status_code, 405)
        self.assertEqual(client.get(self.select_url).status_code, 405)
        self.assertEqual(client.post(self.answer_url, {}).status_code, 403)
        self.assertEqual(client.post(self.select_url, {}).status_code, 403)
        self.assertEqual(client.get(reverse('gift_popup_config')).status_code, 200)
        token = client.cookies['csrftoken'].value
        self.assertEqual(client.post(self.answer_url, {'answer': 'A', 'revision': str(self.config.revision)},
                                    HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_panel_rejects_invalid_discount_delay_and_missing_category(self):
        self.client.force_login(get_user_model().objects.create_user('invalid-gift-manager', is_staff=True))
        response = self.client.post(reverse('panel_section', args=['poklon-pop-up']), {
            'enabled': 'on', 'question': 'Test', 'answer_a': 'A', 'answer_b': 'B',
            'category': self.a.pk, 'percent': 101, 'delay_seconds': -1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context['gift_popup_form'].errors), {'category_b', 'percent', 'delay_seconds'})
