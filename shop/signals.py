from django.conf import settings
from django.db.models.signals import post_save
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
