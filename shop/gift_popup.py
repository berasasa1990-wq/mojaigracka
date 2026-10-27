"""Session-bound gift offers. Prices and eligibility always come from the server."""
from decimal import Decimal, ROUND_HALF_UP
import time

from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import GiftPopupSettings, Product

OFFER_SECONDS = 3600


def current_config():
    return GiftPopupSettings.objects.filter(pk=1, enabled=True, category__isnull=False,
                                            category_b__isnull=False, percent__gt=0, percent__lte=100).first()


def discounted_price(product, percent):
    return (product.price * (1 - percent / 100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def valid_offer(request, config):
    offer = request.session.get('gift_popup_offer')
    if (not config or not isinstance(offer, dict) or offer.get('revision') != str(config.revision)
            or offer.get('expires', 0) <= time.time()):
        return None
    return offer


def active_claim(request):
    if not request.session.get('gift_popup_offer', {}).get('selected'):
        return None
    config = current_config()
    offer = valid_offer(request, config)
    if not offer or offer.get('selected') not in offer.get('products', []):
        return None
    category_id = config.category_id if offer['answer'] == 'A' else config.category_b_id
    return {'product': offer['selected'], 'category': category_id, 'percent': config.percent}


@never_cache
@require_GET
def config_view(request):
    config = current_config()
    if not config:
        return JsonResponse({'enabled': False})
    return JsonResponse({'enabled': True, 'revision': str(config.revision), 'question': config.question,
                         'answer_a': config.answer_a, 'answer_b': config.answer_b,
                         'delay': config.delay_seconds, 'csrf': get_token(request)})


def offer_response(request, config, offer):
    category_id = config.category_id if offer['answer'] == 'A' else config.category_b_id
    products = Product.objects.filter(pk__in=offer['products'], category_id=category_id, is_active=True)
    cards = [{'product': p, 'price': discounted_price(p, config.percent)} for p in products if p.is_available]
    html = render_to_string('shop/partials/gift_popup_offers.html', {
        'cards': cards, 'percent': config.percent, 'selected': offer.get('selected'),
    }, request=request)
    return JsonResponse({'html': html})


@never_cache
@require_POST
def answer_view(request):
    config = current_config()
    answer = request.POST.get('answer')
    if not config or answer not in ('A', 'B') or request.POST.get('revision') != str(config.revision):
        return JsonResponse({'error': 'Ponuda više nije aktivna. Osvježite stranicu.'}, status=400)
    # Repeated requests reuse the original draw and cannot reroll products or extend expiry.
    existing = valid_offer(request, config)
    if existing:
        return offer_response(request, config, existing)
    category_id = config.category_id if answer == 'A' else config.category_b_id
    from bera_licensing.services import module_enabled
    products = Product.objects.filter(category_id=category_id, is_active=True)
    if module_enabled('wms'):
        products = products.filter(stock__gt=0)
    selected = list(products.order_by('?').values_list('pk', flat=True)[:2])
    offer = {'revision': str(config.revision), 'answer': answer, 'products': selected,
             'expires': time.time() + OFFER_SECONDS}
    request.session['gift_popup_offer'] = offer
    return offer_response(request, config, offer)


@never_cache
@require_POST
def select_view(request):
    config = current_config()
    offer = valid_offer(request, config)
    try:
        pk = int(request.POST.get('product', ''))
    except (ValueError, TypeError):
        pk = None
    if not offer or pk not in offer['products']:
        return JsonResponse({'error': 'Poklon ponuda je istekla ili artikal nije ponuđen.'}, status=400)
    if offer.get('selected'):
        if offer['selected'] == pk:
            return redirect('cart')
        return JsonResponse({'error': 'Već ste izabrali poklon artikal.'}, status=400)
    category_id = config.category_id if offer['answer'] == 'A' else config.category_b_id
    product = Product.objects.filter(pk=pk, category_id=category_id, is_active=True).first()
    saved = request.session.get('cart', {}).copy()
    if not product or not product.is_available or saved.get(str(pk), 0) >= product.cart_quantity_limit:
        return JsonResponse({'error': 'Artikal više nije dostupan u traženoj količini.'}, status=400)
    saved[str(pk)] = saved.get(str(pk), 0) + 1
    request.session['cart'] = saved
    request.session['gift_popup_offer'] = {**offer, 'selected': pk}
    return redirect('cart')


def apply_gift_discount(items, claim):
    if not claim:
        return
    for item in items:
        product = item['product']
        if product.pk != claim['product'] or product.category_id != claim['category']:
            continue
        price = discounted_price(product, claim['percent'])
        groups = list(item['promotion_groups'])
        # One unit only; use the better of the existing promotion and gift price.
        index = max(range(len(groups)), key=lambda i: groups[i][0])
        old_price, count, label = groups[index]
        if price >= old_price:
            continue
        groups[index:index + 1] = ([(old_price, count - 1, label)] if count > 1 else []) + [
            (price, 1, f"Poklon pop up (−{claim['percent']:f}%)")]
        item['promotion_groups'] = groups
        item['price_groups'] = [(value, count) for value, count, _ in groups]
        item['subtotal'] = sum((value * count for value, count, _ in groups), Decimal('0.00'))
        item['gift_applied'] = True
        item['gift_percent'] = claim['percent']
