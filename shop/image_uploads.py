"""Bounded, low-CPU image optimization before local or R2 storage."""
from io import BytesIO
from pathlib import Path
import warnings
import logging
import time

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models
from PIL import Image, ImageOps, UnidentifiedImageError, features

MAX_IMAGE_BYTES = 15_000
# Retain legacy field metadata for migration compatibility; forms show current formats.
UPLOAD_HELP = 'Slika se automatski sprema kao AVIF do 15 KB. Po potrebi se smanjuju kvalitet i rezolucija; animacije se spremaju kao prva slika.'


logger = logging.getLogger(__name__)
MAX_SOURCE_PIXELS = 12_000_000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_FALLBACK_ATTEMPTS = 8
FORMAT_DETAILS = {'AVIF': ('.avif', 'image/avif'), 'WEBP': ('.webp', 'image/webp'),
                  'PNG': ('.png', 'image/png')}


def _encode(image, format, **options):
    output = BytesIO()
    image.save(output, format=format, **options)
    return output.getvalue()


def optimize_image(upload, max_bytes=MAX_IMAGE_BYTES, *, max_side=None, prefer_webp=False):
    """Bound encoder work: at most one fast AVIF, then bounded WebP/PNG fallback."""
    max_side = max_side or (1280 if max_bytes > MAX_IMAGE_BYTES else 960)
    policy = (max_bytes, max_side, prefer_webp)
    if getattr(upload, '_optimized_image', None) == policy and upload.size <= max_bytes:
        return upload
    started = time.monotonic()
    attempts = 0
    outcome = 'invalid'
    result_format = '-'
    try:
        if upload.size > MAX_UPLOAD_BYTES:
            raise ValidationError('Slika je prevelika. Najveća veličina uploada je 20 MB.')
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                if source.width * source.height > MAX_SOURCE_PIXELS:
                    raise ValidationError('Slika je prevelike rezolucije. Najviše 12 megapiksela.')
                source.seek(0)  # Keep the existing first-frame animation policy.
                source.draft('RGB', (max_side, max_side))  # JPEG decoder downsampling.
                source.thumbnail((max_side, max_side), Image.Resampling.LANCZOS, reducing_gap=3)
                transposed = ImageOps.exif_transpose(source)
                image = transposed.convert('RGBA' if transposed.has_transparency_data else 'RGB')
        image.info.clear()

        def finish(data, format):
            nonlocal outcome, result_format
            extension, content_type = FORMAT_DETAILS[format]
            result = ContentFile(data, name=Path(upload.name).stem + extension)
            result.content_type = content_type
            result._optimized_image = policy
            outcome, result_format = 'ok', format
            return result

        # Preserve logo edges/alpha losslessly if a cheap PNG already fits.
        if prefer_webp:
            attempts += 1
            data = _encode(image, 'PNG', compress_level=3)
            if len(data) <= max_bytes:
                return finish(data, 'PNG')

        # Pillow 12.3 supports AVIF speed=10 (fastest). Avoid it for logos,
        # alpha artwork and small images; no repeated AVIF quality search.
        if not prefer_webp and image.mode == 'RGB' and max(image.size) > 512 and features.check('avif'):
            attempts += 1
            try:
                data = _encode(image, 'AVIF', quality=55, speed=10, max_threads=1)
                if len(data) <= max_bytes:
                    return finish(data, 'AVIF')
            except (OSError, ValueError, RuntimeError):
                # No filenames, request data, credentials or provider errors.
                logger.warning('image_encode avif_failed elapsed_ms=%.1f fallback=webp_or_png',
                               (time.monotonic() - started) * 1000)

        fallback_format = 'WEBP' if features.check('webp') else 'PNG'
        for attempt in range(MAX_FALLBACK_ATTEMPTS):
            attempts += 1
            try:
                if fallback_format == 'WEBP':
                    data = _encode(image, 'WEBP', quality=max(35, 85 - attempt * 10),
                                   method=0, alpha_quality=100, exact=True)
                else:
                    data = _encode(image, 'PNG', compress_level=3)
            except (OSError, ValueError, RuntimeError):
                if fallback_format == 'PNG':
                    raise ValidationError('Obrada slike nije uspjela. Odaberite drugu sliku.') from None
                logger.warning('image_encode webp_failed elapsed_ms=%.1f fallback=png',
                               (time.monotonic() - started) * 1000)
                fallback_format = 'PNG'
                attempts += 1
                data = _encode(image, 'PNG', compress_level=3)
            if len(data) <= max_bytes:
                return finish(data, fallback_format)
            image = image.resize(tuple(max(1, int(n * .6)) for n in image.size), Image.Resampling.LANCZOS)
        raise ValidationError(f'Slika se ne može smanjiti na {max_bytes // 1000} KB. Odaberite drugu sliku.')
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError('Odaberite ispravnu PNG, JPG, WebP, GIF ili AVIF sliku.') from None
    finally:
        upload.seek(0)
        logger.info('image_encode outcome=%s format=%s attempts=%d elapsed_ms=%.1f',
                    outcome, result_format, attempts, (time.monotonic() - started) * 1000)


class AVIFUploadFormField(forms.FileField):
    def __init__(self, *args, max_bytes=MAX_IMAGE_BYTES, max_side=None, prefer_webp=False, **kwargs):
        self.max_bytes = max_bytes
        self.max_side = max_side
        self.prefer_webp = prefer_webp
        super().__init__(*args, **kwargs)
        self.widget.attrs['accept'] = 'image/png,image/jpeg,image/webp,image/gif,image/avif'

    def clean(self, data, initial=None):
        value = super().clean(data, initial)
        if value and value is not initial:
            return optimize_image(value, self.max_bytes, max_side=self.max_side, prefer_webp=self.prefer_webp)
        return value


class AVIFFileField(models.FileField):
    def __init__(self, *args, max_bytes=MAX_IMAGE_BYTES, **kwargs):
        self.max_bytes = max_bytes
        kwargs.setdefault('help_text', UPLOAD_HELP if max_bytes == MAX_IMAGE_BYTES else f'Slika se automatski sprema kao AVIF do {max_bytes // 1000} KB, uz najviši kvalitet koji stane u zadani limit.')
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.max_bytes != MAX_IMAGE_BYTES:
            kwargs['max_bytes'] = self.max_bytes
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        return super().formfield(**{
            'form_class': AVIFUploadFormField, 'max_bytes': self.max_bytes,
            **self.optimization_options(),
            'help_text': f'Slika se optimizuje do {self.max_bytes // 1000} KB kao PNG, WebP ili AVIF. Animacije koriste prvu sliku.',
            **kwargs,
        })

    def optimization_options(self):
        return {'prefer_webp': self.name == 'logo',
                'max_side': 512 if self.name == 'logo' else (1280 if self.max_bytes > MAX_IMAGE_BYTES else 960)}

    def pre_save(self, model_instance, add):
        file = getattr(model_instance, self.attname)
        if file and not file._committed:
            converted = optimize_image(file.file, self.max_bytes, **self.optimization_options())
            setattr(model_instance, self.attname, converted)
        return super().pre_save(model_instance, add)
