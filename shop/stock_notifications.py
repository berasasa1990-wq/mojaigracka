import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import Product, StockNotification

logger = logging.getLogger(__name__)


def notify_available_product(product_id, using='default'):
    product = Product.objects.using(using).filter(pk=product_id, is_active=True).first()
    if not product or not product.is_available:
        return
    for notification_id in StockNotification.objects.using(using).filter(product=product, notified_at__isnull=True).values_list('pk', flat=True):
        try:
            with transaction.atomic(using=using):
                notification = StockNotification.objects.using(using).select_for_update().get(pk=notification_id)
                if notification.notified_at:
                    continue
                sent = send_mail(
                    f'Ponovo na stanju: {product.name}',
                    f'Artikal {product.name} je ponovo na stanju.\n\nPogledajte artikal: {notification.product_url}',
                    settings.DEFAULT_FROM_EMAIL, [notification.email],
                )
                if sent:
                    notification.notified_at = timezone.now()
                    notification.save(update_fields=['notified_at'], using=using)
        except Exception:
            logger.exception('Slanje obavijesti o stanju nije uspjelo: %s', notification_id)
