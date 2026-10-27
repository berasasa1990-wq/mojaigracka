from decimal import Decimal, ROUND_HALF_UP
from .models import ControlState


def monthly_rebate():
    return ControlState.objects.filter(pk=1).values_list('monthly_rebate', flat=True).first() or Decimal('0')


def discounted_monthly(price, rebate):
    return (Decimal(price) * (1 - rebate / 100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
