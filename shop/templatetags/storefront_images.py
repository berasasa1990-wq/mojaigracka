from hashlib import sha256
from django import template
from django.urls import reverse
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def artwork_sources(item, kind='banner'):
    field = item.logo if kind == 'logo' else item.secondary_image if kind == 'secondary' else item.image
    version = sha256(field.name.encode()).hexdigest()[:12]
    widths = (220, 440) if kind == 'logo' else (400, 800, 1600)
    def url(width):
        return reverse('storefront_image', args=[kind, item.pk, width]) + '?v=' + version
    sizes = '(max-width: 900px) 135px, 220px' if kind == 'logo' else '(max-width: 540px) 100vw, 50vw' if item.position in ('offer_left', 'offer_right') else '100vw'
    return format_html('src="{}" srcset="{}" sizes="{}"', url(widths[0] if kind == 'logo' else 800), ', '.join(f'{url(w)} {w}w' for w in widths), sizes)
