"""Fit visible brand artwork into the same space as the Apple wordmark."""
from functools import lru_cache

from django import template
from django.utils.html import format_html
from PIL import Image, ImageChops
from botocore.exceptions import BotoCoreError, ClientError

register = template.Library()


@lru_cache(maxsize=256)
def logo_geometry(storage, name, version):
    with storage.open(name, "rb") as artwork, Image.open(artwork) as source:
        image = source.convert('RGBA')
        white = Image.new('RGBA', image.size, 'white')
        white.alpha_composite(image)
        difference = ImageChops.difference(white.convert('RGB'), Image.new('RGB', image.size, 'white'))
        bounds = difference.convert('L').point(lambda value: 255 if value > 35 else 0).getbbox()
        left, top, right, bottom = bounds or (0, 0, *image.size)
        scale = min(54 / (right - left), 23.3 / (bottom - top))
        return tuple(f'{value:.3f}' for value in (
            image.width * scale, image.height * scale,
            -left * scale, (24 - (bottom - top) * scale) / 2 - top * scale,
        ))


@register.simple_tag
def brand_logo(brand):
    try:
        storage = brand.logo.storage
        version = storage.get_modified_time(brand.logo.name)
        width, height, left, top = logo_geometry(storage, brand.logo.name, version)
    except (OSError, ValueError, NotImplementedError, BotoCoreError, ClientError):
        return format_html('<img src="{}" alt="{}" loading="lazy">', brand.logo.url, brand.name)
    return format_html(
        '<span class="normalized-brand"><img src="{}" alt="{}" loading="lazy" style="width:{}px;height:{}px;left:{}px;top:{}px"></span>',
        brand.logo.url, brand.name, width, height, left, top,
    )
