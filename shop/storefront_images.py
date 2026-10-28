"""Bounded responsive images for existing and new storefront artwork."""
from hashlib import sha256
from io import BytesIO
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from PIL import Image, ImageOps, UnidentifiedImageError
from .models import Banner, StoreSettings


def storefront_image(request, kind, pk, width):
    if kind == 'logo' and width in (220, 440):
        file = get_object_or_404(StoreSettings, pk=pk).logo
        limit = 30_000
    elif kind in ('banner', 'secondary') and width in (400, 800, 1600):
        banner = get_object_or_404(Banner, pk=pk, is_active=True)
        file = banner.secondary_image if kind == 'secondary' else banner.image
        limit = {400: 30_000, 800: 65_000, 1600: 130_000}[width]
    else:
        raise Http404
    if not file:
        raise Http404
    key = f'storefront-image-v1:{width}:{limit}:' + sha256(file.name.encode()).hexdigest()
    data = cache.get(key)
    if data is None:
        try:
            with file.open('rb') as source, Image.open(source) as original:
                if original.width * original.height > 12_000_000:
                    raise Http404
                frame = ImageOps.exif_transpose(original)
                frame.thumbnail((width, width), Image.Resampling.LANCZOS)
                frame = frame.convert('RGBA' if frame.has_transparency_data else 'RGB')
                frame.info.clear()
                while True:
                    for quality in (85, 75, 65):
                        output = BytesIO()
                        frame.save(output, 'WEBP', quality=quality, method=4)
                        data = output.getvalue()
                        if len(data) <= limit:
                            break
                    if len(data) <= limit:
                        break
                    frame.thumbnail((max(1, frame.width * 3 // 4), max(1, frame.height * 3 // 4)), Image.Resampling.LANCZOS)
        except (OSError, ValueError, UnidentifiedImageError):
            raise Http404 from None
        cache.set(key, data, 86400)
    response = HttpResponse(data, content_type='image/webp')
    response['Cache-Control'] = 'public, max-age=86400'
    response['Content-Length'] = str(len(data))
    return response
