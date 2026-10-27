from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import LoyaltyCard


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_loyalty_card(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        if 'loyalty' in settings.BERA_LICENSE_ENFORCED_MODULES:
            from bera_licensing.services import module_enabled
            if not module_enabled('loyalty'):
                return
        LoyaltyCard.objects.get_or_create(customer=instance)


from .models import Order
from .models import Product


@receiver(pre_save, sender=Product)
def remember_stock(sender, instance, raw=False, update_fields=None, using='default', **kwargs):
    if raw or (update_fields is not None and 'stock' not in update_fields):
        return
    instance._stock_before = sender.objects.using(using).filter(pk=instance.pk).values_list('stock', flat=True).first() if instance.pk else 0


@receiver(post_save, sender=Product)
def record_stock_movement(sender, instance, raw=False, update_fields=None, using='default', **kwargs):
    if raw or (update_fields is not None and 'stock' not in update_fields):
        return
    before = getattr(instance, '_stock_before', 0) or 0
    if instance.stock != before:
        from wms.models import StockMovement
        StockMovement.objects.using(using).create(
            product=instance, product_name=instance.name, change=instance.stock - before,
            stock_before=before, stock_after=instance.stock,
            reason=getattr(instance, '_stock_reason', '') or 'Ručna izmjena količine artikla',
        )


@receiver(post_save, sender=Order)
def update_order_points(sender, instance, raw=False, **kwargs):
    from .modules import loyalty_enabled
    if not raw and loyalty_enabled():
        from .loyalty import settle_points
        settle_points(instance.pk)


@receiver(post_save, sender=Product)
def send_stock_notifications(sender, instance, raw=False, using='default', update_fields=None, **kwargs):
    if raw or (update_fields is not None and not {'stock', 'is_out_of_stock', 'is_active'}.intersection(update_fields)):
        return
    from django.db import transaction
    from .stock_notifications import notify_available_product
    transaction.on_commit(lambda: notify_available_product(instance.pk, using), using=using)
