from django.core.management.base import BaseCommand
from shop.models import StockNotification
from shop.stock_notifications import notify_available_product


class Command(BaseCommand):
    help = 'Ponovo pokušaj slanje neisporučenih obavijesti za dostupne artikle.'

    def handle(self, *args, **options):
        for product_id in StockNotification.objects.filter(notified_at__isnull=True).values_list('product_id', flat=True).distinct():
            notify_available_product(product_id)
