"""Quality-first, bounded product derivatives. No remote I/O during encoding."""
from io import BytesIO
import logging
from pathlib import Path
import time
import uuid
import warnings

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError, features

PROFILES = {'thumbnail': (300, (10_000, 15_000)), 'card': (500, (15_000, 30_000)),
            'main': (800, (30_000, 60_000))}
VERSION = 1
logger = logging.getLogger(__name__)


class ProductImageUploadError(ValidationError):
    pass


def _srgb(image):
    """Use the input profile before discarding metadata; retain the alpha plane."""
    if image.mode.startswith('I;16') or (image.mode == 'I' and image.getextrema()[1] > 255):
        image = image.convert('I').point(lambda value: value / 257).convert('L')
    alpha = image.getchannel('A') if image.mode == 'RGBA' else None
    profile = image.info.get('icc_profile')
    if profile:
        try:
            color = image.convert('RGB') if alpha is not None else image
            color = ImageCms.profileToProfile(color, ImageCms.ImageCmsProfile(BytesIO(profile)),
                                             ImageCms.createProfile('sRGB'), outputMode='RGB')
            if alpha is not None:
                color.putalpha(alpha)
            return color
        except (OSError, ValueError, ImageCms.PyCMSError):
            logger.warning('product_image invalid_color_profile fallback=rgb')
    return image.convert('RGBA' if image.has_transparency_data else 'RGB')


def prepare_product_image(upload):
    if getattr(upload, '_product_image_version', None) == VERSION:
        return upload
    from .image_uploads import MAX_SOURCE_PIXELS, MAX_UPLOAD_BYTES, _encode
    started = time.monotonic()
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError('Slika je prevelika. Najveća veličina uploada je 20 MB.')
    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP', 'GIF', 'AVIF'):
                    raise ValidationError('Odaberite PNG, JPG, WebP, GIF ili AVIF sliku.')
                if source.width * source.height > MAX_SOURCE_PIXELS:
                    raise ValidationError('Slika je prevelike rezolucije. Najviše 12 megapiksela.')
                source.seek(0)  # Product derivatives use the first animation frame.
                if source.mode in ('RGB', 'L'):
                    source.draft('RGB', (800, 800))
                ImageOps.exif_transpose(source, in_place=True)
                # Downsample before allocating color-managed RGB copies. Palette
                # and 16-bit sources need a resample-capable mode first.
                working = source
                if source.mode in ('P', 'PA', '1'):
                    working = source.convert('RGBA' if source.has_transparency_data else 'RGB')
                elif source.mode.startswith('I;16') or source.mode == 'I':
                    working = _srgb(source)
                working.thumbnail((800, 800), Image.Resampling.LANCZOS, reducing_gap=3)
                image = _srgb(working)
        image.info.clear()
        if not features.check('webp'):
            raise ValidationError('WebP obrada nije dostupna. Pokušajte kasnije.')
        derivatives = {}
        avif_probe_ms = None
        for label, (side, target) in PROFILES.items():
            frame = image.copy()
            frame.thumbnail((side, side), Image.Resampling.LANCZOS, reducing_gap=3)
            frame.info.clear()
            # Fixed quality: targets are reporting hints, never a reason to blur.
            data = _encode(frame, 'WEBP', quality=85, method=0, alpha_quality=100, exact=True)
            format, mime, extension = 'WEBP', 'image/webp', '.webp'
            # At most ONE AVIF attempt per upload, on the <=300px thumbnail only.
            # Opt in only after measuring the actual worker; default is WebP.
            if (label == 'thumbnail' and getattr(settings, 'PRODUCT_IMAGE_TRY_AVIF', False)
                    and features.check('avif') and time.monotonic() - started < 1):
                probe_started = time.monotonic()
                try:
                    avif = _encode(frame, 'AVIF', quality=85, speed=10, max_threads=1, subsampling='4:4:4')
                    elapsed = time.monotonic() - probe_started
                    avif_probe_ms = elapsed * 1000
                    if elapsed <= settings.PRODUCT_IMAGE_AVIF_MAX_SECONDS and len(avif) < len(data):
                        data, format, mime, extension = avif, 'AVIF', 'image/avif', '.avif'
                    logger.info('product_image avif_probe elapsed_ms=%.1f selected=%s', elapsed * 1000, format)
                except (OSError, ValueError, RuntimeError):
                    logger.warning('product_image avif_failed fallback=webp')
            file = ContentFile(data, name=Path(upload.name).stem + extension)
            file.content_type = mime
            derivatives[label] = {'file': file, 'width': frame.width, 'height': frame.height,
                                  'bytes': len(data), 'format': format, 'mime': mime,
                                  'target': list(target)}
            logger.info('product_image variant=%s format=%s width=%d height=%d bytes=%d target_max=%d',
                        label, format, frame.width, frame.height, len(data), target[1])
        main = derivatives['main']['file']
        main._product_image_version = VERSION
        main._product_derivatives = derivatives
        main._product_upload_id = uuid.uuid4().hex[:12]
        main._product_avif_probe_ms = avif_probe_ms
        main._product_processing_ms = (time.monotonic() - started) * 1000
        logger.info('product_image outcome=ok elapsed_ms=%.1f', main._product_processing_ms)
        return main
    except (OSError, ValueError, RuntimeError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError('Obrada slike nije uspjela. Odaberite ispravnu sliku.') from None
    finally:
        upload.seek(0)


def image_sources(file, manifest, fallback_url=None):
    """Use only matching manifests. Old images never get generated on reads."""
    fallback = fallback_url if fallback_url is not None else (file.url if file else '')
    result = {'url': fallback, 'thumbnail_url': fallback, 'thumbnail_fallback_url': fallback,
              'thumbnail_avif_url': '', 'card_url': fallback, 'srcset': ''}
    if not file or not manifest or manifest.get('source') != file.name:
        return result
    entries = [manifest.get(label, {}) for label in PROFILES]
    if not all(entry.get('name') and entry.get('width') for entry in entries):
        return result
    urls = {label: file.storage.url(manifest[label]['name']) for label in PROFILES}
    # Do not mix codecs in one img srcset: browsers cannot negotiate its type.
    by_width = {int(manifest[label]['width']): urls[label] for label in PROFILES
                if manifest[label].get('format') == 'WEBP'}
    avif_thumbnail = manifest['thumbnail'].get('format') == 'AVIF'
    result.update(url=urls['main'], thumbnail_url=urls['thumbnail'], card_url=urls['card'],
                  thumbnail_fallback_url=urls['card'] if avif_thumbnail else urls['thumbnail'],
                  thumbnail_avif_url=urls['thumbnail'] if avif_thumbnail else '',
                  srcset=', '.join(f'{url} {width}w' for width, url in sorted(by_width.items())),
                  width=manifest['main']['width'], height=manifest['main']['height'])
    return result


class ProductImageVariantsMixin:
    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'image' in update_fields:
            kwargs['update_fields'] = set(update_fields) | {'image_variants'}
        return super().save(*args, **kwargs)
