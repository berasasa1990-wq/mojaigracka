"""Serve public images with a site-branded suggested download filename."""
from pathlib import Path
import re

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.utils.http import content_disposition_header
from django.utils.html import strip_tags
from django.utils.text import slugify
from django.views.static import serve

from .models import SEOSettings

IMAGE_EXTENSIONS = {'.avif', '.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.ico', '.bmp'}


def image_download_name(path):
    config = SEOSettings.objects.filter(pk=1).first()
    name = config.site_name if config else 'BERA'
    description = ' '.join(strip_tags(config.description if config else '').split())
    first_sentence = re.split(r'[.!?](?:\s|$)', description, maxsplit=1)[0]
    stem = slugify(f'{name} {first_sentence}')[:180].rstrip('-') or 'slika'
    return stem + Path(path).suffix.lower()


def public_image(request, path, **kwargs):
    if Path(path).suffix.lower() not in IMAGE_EXTENSIONS:
        raise Http404('Slika nije pronađena.')
    if getattr(settings, 'R2_IMAGES_ENABLED', False):
        from .storage import PUBLIC_PREFIXES, public_image_storage
        if not path.startswith(PUBLIC_PREFIXES) or '..' in Path(path).parts or '\\' in path:
            raise Http404('Slika nije pronađena.')
        if request.GET.get('proxy') == '1':
            import logging
            import mimetypes
            from botocore.exceptions import BotoCoreError, ClientError
            try:
                image = public_image_storage().open(path, 'rb')
            except (FileNotFoundError, OSError):
                raise Http404('Slika nije pronađena.') from None
            except ClientError as error:
                code = str(error.response.get('Error', {}).get('Code', ''))
                if code in ('404', 'NoSuchKey', 'NotFound'):
                    raise Http404('Slika nije pronađena.') from None
                logging.getLogger(__name__).warning('public_image_proxy storage_unavailable')
                response = HttpResponse(status=502)
                response['Cache-Control'] = 'no-store'
                return response
            except BotoCoreError:
                logging.getLogger(__name__).warning('public_image_proxy storage_unavailable')
                response = HttpResponse(status=502)
                response['Cache-Control'] = 'no-store'
                return response
            content_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            response = FileResponse(image, content_type=content_type)
            response['Content-Disposition'] = content_disposition_header(False, image_download_name(path))
            response['Cache-Control'] = 'public, max-age=3600'
            response['X-Content-Type-Options'] = 'nosniff'
            response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
            return response
        # Preserve old public media links without copying private files to R2.
        return HttpResponseRedirect(public_image_storage().url(path))
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    if response.status_code == 200:
        response['Content-Disposition'] = content_disposition_header(False, image_download_name(path))
    return response


def product_share_image(request, pk):
    """A JPEG social preview with the full product fitted onto a white canvas."""
    from io import BytesIO
    from PIL import Image, ImageOps, UnidentifiedImageError
    from django.core.cache import cache
    from django.http import HttpResponse
    from django.shortcuts import get_object_or_404
    from django.utils.crypto import salted_hmac
    from .models import Product

    product = get_object_or_404(Product, pk=pk, is_active=True)
    if not product.image:
        raise Http404
    key = 'product-share:' + salted_hmac('share-image', product.image.name).hexdigest()
    data = cache.get(key)
    if data is None:
        try:
            with product.image.open('rb') as source, Image.open(source) as original:
                artwork = ImageOps.exif_transpose(original).convert('RGBA')
                artwork = ImageOps.contain(artwork, (1040, 510), Image.Resampling.LANCZOS)
                canvas = Image.new('RGB', (1200, 630), 'white')
                canvas.paste(artwork, ((1200 - artwork.width) // 2, (630 - artwork.height) // 2), artwork)
                output = BytesIO()
                canvas.save(output, 'JPEG', quality=90, optimize=True)
                data = output.getvalue()
        except (OSError, ValueError, UnidentifiedImageError):
            raise Http404('Slika nije dostupna.')
        cache.set(key, data, 3600)
    response = HttpResponse(data, content_type='image/jpeg')
    response['Cache-Control'] = 'public, max-age=3600'
    return response
