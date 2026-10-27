from django import template

from shop.models import Brand, Order

register = template.Library()


@register.simple_tag(takes_context=True)
def panel_module_locked(context, item):
    code = item.get('module_code')
    if not code:
        return False
    for module in context.get('bera_modules', []):
        if module['code'] == code:
            return not module['enabled']
    from bera_licensing.services import module_enabled
    return not module_enabled(code)


@register.simple_tag
def new_orders_count():
    return Order.objects.filter(status='placed').count()


@register.simple_tag
def all_store_brands():
    return Brand.objects.all()


@register.simple_tag
def panel_css_version():
    from django.conf import settings
    return (settings.BASE_DIR / 'shop/static/css/panel.css').stat().st_mtime_ns


@register.simple_tag
def public_image_domain():
    from shop.storage import public_image_storage
    return getattr(public_image_storage(), 'custom_domain', '') or ''


@register.simple_tag
def public_media_url():
    from django.conf import settings
    return settings.MEDIA_URL
