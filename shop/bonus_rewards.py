from datetime import timedelta

from django.utils import timezone

from .models import BonusRewardOffer


def eligible_order(order):
    return order and order.status == 'placed' and order.created_at >= timezone.now() - timedelta(hours=1)


def offers_for(order):
    if not eligible_order(order):
        return []
    from bera_licensing.services import module_enabled
    if not module_enabled('bonus_reward'):
        return []
    offers = BonusRewardOffer.objects.filter(is_active=True, product__is_active=True).exclude(
        pk__in=order.bonus_rewards.values_list('offer_id', flat=True)
    ).select_related('product')
    return [offer for offer in offers if offer.product.is_available][:4]
