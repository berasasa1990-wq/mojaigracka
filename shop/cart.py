from decimal import Decimal, ROUND_HALF_UP
from .models import Product, StoreSettings


def cart_context(request):
    saved = request.session.get('cart', {})
    products = list(Product.objects.filter(pk__in=saved, is_active=True).select_related('brand', 'plus_product'))
    quantities = {str(p.pk): min(saved[str(p.pk)], p.cart_quantity_limit) for p in products if p.is_available}
    if request.method == 'GET' and saved != quantities:
        request.session['cart'] = quantities
    from .gift_popup import active_claim
    items = priced_items(products, quantities, gift_claim=active_claim(request))
    for item in items:
        item['plus_offer'] = article_plus_offer(item['product'], quantities)
        item['quantity_offers'] = quantity_offers(item['product'], item['quantity'])
    if not items:
        # A new basket must not inherit a previous loyalty selection.
        request.session.pop('loyalty_customer', None)
        request.session.pop('cart_loyalty_points', None)
    store = StoreSettings.objects.filter(pk=1).first()
    subtotal = sum((i['subtotal'] for i in items), Decimal('0.00'))
    from .loyalty import loyalty_status, loyalty_amount, applied_loyalty_percent, rules
    _, available_percent = loyalty_status(request.user)
    percent = applied_loyalty_percent(request)
    applied = request.user.is_authenticated and request.session.get('loyalty_customer') == request.user.pk
    eligible = loyalty_eligible_total(items)
    discount = loyalty_amount(eligible, percent)
    delivery = store.delivery_cost(subtotal - discount) if store and items else Decimal('0.00')
    from .modules import loyalty_enabled
    from .models import LoyaltyCard
    card = LoyaltyCard.objects.filter(customer=request.user).first() if request.user.is_authenticated and loyalty_enabled() else None
    return {'gift_wrap_selected': request.session.get('gift_packaging') == 'folija', 'loyalty_eligible_total': eligible, 'loyalty_has_sale_items': eligible < subtotal, 'loyalty_rules': rules(), 'points_balance': max(0, card.points) if card else 0, 'loyalty_enabled': loyalty_enabled(), 'loyalty_available_percent': available_percent, 'loyalty_applied': applied, 'delivery_price': delivery, 'loyalty_percent': percent, 'loyalty_discount': discount, 'grand_total': subtotal - discount + delivery, 'cart_items': items, 'cart_count': sum(i['quantity'] for i in items),
            'cart_total': subtotal}


def priced_items(products, quantities, *, gift_claim=None):
    """One discounted second item per regular first item; use the best offer first."""
    products = {p.pk: p for p in products if quantities.get(str(p.pk), 0) > 0}
    offers = {}
    for first in products.values():
        if (first.has_article_plus and first.plus_product_id in products
                and first.plus_percent and not (first.original_price and first.original_price > first.price)
                and first.plus_product_id != first.pk):
            offers.setdefault(first.plus_product_id, []).append(first)
    items = []
    for product in products.values():
        quantity = quantities[str(product.pk)]
        quantity_percent = product.quantity_discount_percent(quantity)
        quantity_price = (product.price * (1 - Decimal(quantity_percent) / 100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        remaining = quantity
        groups = []
        plus_discounts = []
        promotion_groups = []
        for first in sorted(offers.get(product.pk, []), key=lambda p: p.plus_percent, reverse=True):
            count = min(remaining, quantities[str(first.pk)])
            price = (product.price * (1 - first.plus_percent / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if count and price < quantity_price:
                groups.append((price, count))
                promotion_groups.append((price, count, f"Ponuda +: {first.name} (−{Decimal(str(first.plus_percent)).normalize():f}%)"))
                plus_discounts.append({'price': price, 'quantity': count, 'percent': first.plus_percent})
                remaining -= count
        if remaining:
            groups.append((quantity_price, remaining))
            labels = []
            if product.original_price and product.original_price > product.price:
                labels.append(f'Regularno sniženje (−{product.discount_percent}%)')
            if quantity_percent:
                labels.append(f'Količinsko sniženje: {quantity} kom (−{Decimal(str(quantity_percent)).normalize():f}%)')
            promotion_groups.append((quantity_price, remaining, '; '.join(labels)))
        items.append({'product': product, 'quantity': quantity, 'price_groups': groups, 'promotion_groups': promotion_groups, 'plus_discounts': plus_discounts, 'regular_quantity': remaining, 'quantity_percent': quantity_percent, 'quantity_price': quantity_price,
                      'subtotal': sum((price * count for price, count in groups), Decimal('0.00'))})
    apply_bundle_discounts(items, products, quantities)
    from .gift_popup import apply_gift_discount
    apply_gift_discount(items, gift_claim)
    apply_custom_set_discount(items)
    return items


def article_plus_offer(product, saved):
    if not product.has_article_plus or not product.is_available:
        return None
    second = product.plus_product
    first_quantity = saved.get(str(product.pk), 0)
    second_quantity = saved.get(str(second.pk), 0)
    limit = second.cart_quantity_limit
    if not second.is_available or first_quantity <= second_quantity or second_quantity >= limit:
        return None
    price = (second.price * (1 - product.plus_percent / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    from django.urls import reverse
    return {'name': second.name, 'percent': format(product.plus_percent.normalize(), 'f'),
            'price': f'{price:.2f}', 'regular_price': f'{second.price:.2f}',
            'url': second.get_absolute_url(), 'add_url': reverse('cart_update', args=[second.pk]),
            'image': second.image_thumbnail_url if second.image else '', 'first_name': product.name}


def quantity_offers(product, current_quantity):
    if not product.has_quantity_sale:
        return []
    limit = product.cart_quantity_limit
    result = []
    for quantity, label in [(2, '2 kom'), (3, '3 kom'), (max(4, current_quantity), 'Preko 3 kom')]:
        percent = product.quantity_discount_percent(quantity)
        if percent <= 0 or quantity > limit:
            continue
        price = (product.price * (1 - Decimal(percent) / 100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        result.append({'quantity': quantity, 'label': label, 'percent': percent, 'price': price,
                       'total': price * quantity, 'selected': current_quantity == quantity})
    return result


def apply_bundle_discounts(items, products, quantities):
    from bera_licensing.services import module_enabled
    if not module_enabled('bundle'):
        return
    # Compare each unit against other promotions; discounts never compound.
    units = {item['product'].pk: [dict(price=price, bundle=None, promotion=label) for price, count, label in item['promotion_groups'] for _ in range(count)] for item in items}
    for anchor in sorted(products.values(), key=lambda p: p.bundle_percent or 0, reverse=True):
        if anchor.sale_type != 'bundle' or not anchor.bundle_percent or not 0 < anchor.bundle_percent <= 100:
            continue
        members = list(anchor.bundle_products.all())
        member_ids = {anchor.pk, *(member.pk for member in members)}
        if not members or len(member_ids) != len(members) + 1 or any(pk not in products or not products[pk].is_active or not products[pk].is_available for pk in member_ids):
            continue
        count = min(quantities[str(pk)] for pk in member_ids)
        for pk in member_ids:
            product = products[pk]
            price = (product.price * (1 - anchor.bundle_percent / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            for unit in sorted(units[pk], key=lambda u: u['price'], reverse=True)[:count]:
                if price < unit['price']:
                    unit['price'] = price
                    unit['bundle'] = anchor.bundle_percent
                    unit['promotion'] = f'Bundle set: {anchor.name} (−{Decimal(str(anchor.bundle_percent)).normalize():f}%)'
    for item in items:
        values = units[item['product'].pk]
        item['bundle_applied'] = any(unit['bundle'] is not None for unit in values)
        if item['bundle_applied']:
            groups = {}
            for unit in values:
                groups[unit['price']] = groups.get(unit['price'], 0) + 1
            item['price_groups'] = list(groups.items())
            promotions = {}
            for unit in values:
                key = (unit['price'], unit['promotion'])
                promotions[key] = promotions.get(key, 0) + 1
            item['promotion_groups'] = [(price, count, label) for (price, label), count in promotions.items()]
            item['subtotal'] = sum((price * count for price, count in item['price_groups']), Decimal('0.00'))
            item['bundle_percent'] = max(unit['bundle'] or 0 for unit in values)


def checkout_points_context(request, context, requested=0):
    from .loyalty import point_quote
    net = context['cart_total'] - context['loyalty_discount']
    eligible_net = max(Decimal('0'), context['loyalty_eligible_total'] - context['loyalty_discount'])
    used, discount = point_quote(request.user, eligible_net, requested)
    allowed, _ = point_quote(request.user, eligible_net, context['points_balance'])
    store = StoreSettings.objects.filter(pk=1).first()
    delivery = store.delivery_cost(net - discount) if store and context['cart_items'] else Decimal('0.00')
    return {
        'points_used': used, 'points_discount': discount, 'points_allowed': allowed,
        'delivery_price': delivery, 'grand_total': net - discount + delivery,
    }


def selected_cart_points(request):
    selection = request.session.get('cart_loyalty_points', {})
    if request.user.is_authenticated and selection.get('customer') == request.user.pk:
        return selection.get('points', 0)
    return 0


def apply_custom_set_discount(items):
    from .models import CustomSetOffer
    units = []
    for item in items:
        for price, count, label in item['promotion_groups']:
            units.extend((item, price, label) for _ in range(count))
    # Highest-priced units form full sets first; leftover units keep their price.
    ordered = sorted(range(len(units)), key=lambda i: (-units[i][0]['product'].price, units[i][0]['product'].pk))
    best = None
    best_saving = Decimal('0')
    for offer in CustomSetOffer.objects.filter(is_active=True):
        if offer.quantity < 2 or not 0 < offer.percent <= 100:
            continue
        eligible = ordered[:len(units) // offer.quantity * offer.quantity]
        prices = {}
        saving = Decimal('0')
        for index in eligible:
            item, current, _ = units[index]
            price = (item['product'].price * (1 - offer.percent / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if price < current:
                prices[index] = price
                saving += current - price
        if saving > best_saving:
            best_saving, best = saving, (offer, prices)
    if best is None:
        return
    offer, prices = best
    label = f'{offer.name}: set {offer.quantity} artikla (−{offer.percent.normalize():f}%)'
    for item in items:
        groups = {}
        for index, (owner, price, promotion) in enumerate(units):
            if owner is not item:
                continue
            if index in prices:
                price, promotion = prices[index], label
                item['custom_set_label'] = label
            groups[(price, promotion)] = groups.get((price, promotion), 0) + 1
        item['promotion_groups'] = [(price, count, promotion) for (price, promotion), count in groups.items()]
        item['price_groups'] = [(price, count) for price, count, _ in item['promotion_groups']]
        item['subtotal'] = sum((price * count for price, count in item['price_groups']), Decimal('0'))


def loyalty_eligible_total(items):
    """Loyalty applies only to units without a sale or promotion discount."""
    total = Decimal('0')
    for item in items:
        product = item['product']
        if product.original_price and product.original_price > product.price:
            continue
        total += sum((price * count for price, count, label in item['promotion_groups']
                      if price >= product.price), Decimal('0'))
    return total
