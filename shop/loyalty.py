from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, F, Q
from .models import LoyaltyTier


def loyalty_status(user):
    from .modules import loyalty_enabled
    if not user.is_authenticated or not loyalty_enabled():
        return Decimal('0'), Decimal('0')
    spent = user.shop_orders.filter(status__in=['placed', 'completed']).aggregate(value=Sum(F('total') - F('delivery_price')))['value'] or Decimal('0')
    tier = LoyaltyTier.objects.filter(minimum__lte=spent).filter(Q(maximum__isnull=True) | Q(maximum__gt=spent)).order_by('-minimum').first()
    return spent, tier.percent if tier else Decimal('0')


def loyalty_amount(subtotal, percent):
    return (subtotal * percent / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def applied_loyalty_percent(request):
    if request.user.is_authenticated and request.session.get('loyalty_customer') == request.user.pk:
        return loyalty_status(request.user)[1]
    return Decimal('0')
