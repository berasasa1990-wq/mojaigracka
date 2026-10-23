from decimal import Decimal, ROUND_HALF_UP
from .models import Product, StoreSettings


def cart_context(request):
    saved = request.session.get('cart', {})
    products = list(Product.objects.filter(pk__in=saved, is_active=True).select_related('brand', 'plus_product'))
    quantities = {str(p.pk): min(saved[str(p.pk)], p.stock if p.stock else 99, 99) for p in products if not p.is_out_of_stock}
    items = priced_items(products, quantities)
    for item in items:
        item['plus_offer'] = article_plus_offer(item['product'], quantities)
        item['quantity_offers'] = quantity_offers(item['product'], item['quantity'])
    store = StoreSettings.objects.filter(pk=1).first()
    subtotal = sum((i['subtotal'] for i in items), Decimal('0.00'))
    from .loyalty import loyalty_status, loyalty_amount, applied_loyalty_percent
    _, available_percent = loyalty_status(request.user)
    percent = applied_loyalty_percent(request)
    applied = request.user.is_authenticated and request.session.get('loyalty_customer') == request.user.pk
    discount = loyalty_amount(subtotal, percent)
    delivery = store.delivery_cost(subtotal - discount) if store and items else Decimal('0.00')
    from .modules import loyalty_enabled
    return {'loyalty_enabled': loyalty_enabled(), 'loyalty_available_percent': available_percent, 'loyalty_applied': applied, 'delivery_price': delivery, 'loyalty_percent': percent, 'loyalty_discount': discount, 'grand_total': subtotal - discount + delivery, 'cart_items': items, 'cart_count': sum(i['quantity'] for i in items),
            'cart_total': subtotal}


def priced_items(products, quantities):
    """One discounted second item per regular first item; use the best offer first."""
    products = {p.pk: p for p in products if quantities.get(str(p.pk), 0) > 0}
    offers = {}
    for first in products.values():
        if (first.sale_type == 'article_plus' and first.plus_product_id in products
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
        for first in sorted(offers.get(product.pk, []), key=lambda p: p.plus_percent, reverse=True):
            count = min(remaining, quantities[str(first.pk)])
            price = (product.price * (1 - first.plus_percent / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if count and price < quantity_price:
                groups.append((price, count))
                plus_discounts.append({'price': price, 'quantity': count, 'percent': first.plus_percent})
                remaining -= count
        if remaining:
            groups.append((quantity_price, remaining))
        items.append({'product': product, 'quantity': quantity, 'price_groups': groups, 'plus_discounts': plus_discounts, 'regular_quantity': remaining, 'quantity_percent': quantity_percent, 'quantity_price': quantity_price,
                      'subtotal': sum((price * count for price, count in groups), Decimal('0.00'))})
    apply_bundle_discounts(items, products, quantities)
    return items


def article_plus_offer(product, saved):
    if not product.has_article_plus or product.is_out_of_stock:
        return None
    second = product.plus_product
    first_quantity = saved.get(str(product.pk), 0)
    second_quantity = saved.get(str(second.pk), 0)
    limit = min(second.stock if second.stock else 99, 99)
    if second.is_out_of_stock or first_quantity <= second_quantity or second_quantity >= limit:
        return None
    price = (second.price * (1 - product.plus_percent / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    from django.urls import reverse
    return {'name': second.name, 'percent': format(product.plus_percent.normalize(), 'f'),
            'price': f'{price:.2f}', 'regular_price': f'{second.price:.2f}',
            'url': second.get_absolute_url(), 'add_url': reverse('cart_update', args=[second.pk]),
            'image': second.image.url if second.image else '', 'first_name': product.name}


def quantity_offers(product, current_quantity):
    if product.sale_type != 'quantity':
        return []
    limit = min(product.stock if product.stock else 99, 99)
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
    # Compare each unit against other promotions; discounts never compound.
    units = {item['product'].pk: [dict(price=price, bundle=None) for price, count in item['price_groups'] for _ in range(count)] for item in items}
    for anchor in sorted(products.values(), key=lambda p: p.bundle_percent or 0, reverse=True):
        if anchor.sale_type != 'bundle' or not anchor.bundle_percent or not 0 < anchor.bundle_percent <= 100:
            continue
        members = list(anchor.bundle_products.all())
        member_ids = {anchor.pk, *(member.pk for member in members)}
        if not members or len(member_ids) != len(members) + 1 or any(pk not in products or not products[pk].is_active or products[pk].is_out_of_stock for pk in member_ids):
            continue
        count = min(quantities[str(pk)] for pk in member_ids)
        for pk in member_ids:
            product = products[pk]
            price = (product.price * (1 - anchor.bundle_percent / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            for unit in sorted(units[pk], key=lambda u: u['price'], reverse=True)[:count]:
                if price < unit['price']:
                    unit['price'] = price
                    unit['bundle'] = anchor.bundle_percent
    for item in items:
        values = units[item['product'].pk]
        item['bundle_applied'] = any(unit['bundle'] is not None for unit in values)
        if item['bundle_applied']:
            groups = {}
            for unit in values:
                groups[unit['price']] = groups.get(unit['price'], 0) + 1
            item['price_groups'] = list(groups.items())
            item['subtotal'] = sum((price * count for price, count in item['price_groups']), Decimal('0.00'))
            item['bundle_percent'] = max(unit['bundle'] or 0 for unit in values)
