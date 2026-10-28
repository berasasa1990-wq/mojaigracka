"""Cached brand logos capped at 30 KB, including existing uploads."""
from hashlib import sha256
from io import BytesIO

from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import Brand

MAX_BYTES = 30_000


def brand_logo_image(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if not brand.logo:
        raise Http404
    key = 'brand-logo-v1:' + sha256(brand.logo.name.encode()).hexdigest()
    data = cache.get(key)
    if data is None:
        try:
            with brand.logo.open('rb') as source, Image.open(source) as original:
                if original.width * original.height > 12_000_000:
                    raise Http404
                frame = ImageOps.exif_transpose(original)
                frame.thumbnail((400, 400), Image.Resampling.LANCZOS)
                frame = frame.convert('RGBA' if frame.has_transparency_data else 'RGB')
                frame.info.clear()
                while True:
                    for quality in (85, 75, 65):
                        output = BytesIO()
                        frame.save(output, 'WEBP', quality=quality, method=4)
                        data = output.getvalue()
                        if len(data) <= MAX_BYTES:
                            break
                    if len(data) <= MAX_BYTES:
                        break
                    frame.thumbnail((max(1, frame.width * 3 // 4), max(1, frame.height * 3 // 4)), Image.Resampling.LANCZOS)
        except (OSError, ValueError, UnidentifiedImageError):
            raise Http404 from None
        cache.set(key, data, 86400)
    response = HttpResponse(data, content_type='image/webp')
    response['Cache-Control'] = 'public, max-age=86400'
    response['Content-Length'] = str(len(data))
    return response
