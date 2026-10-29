from django import template
from shop.seo import metadata
register = template.Library()


@register.simple_tag(takes_context=True)
def seo_metadata(context):
    return metadata(context)


@register.simple_tag(takes_context=True)
def seo_site_name(context):
    from shop.seo import settings_for
    return settings_for(context['request']).site_name or 'Mojaigracka.com'
