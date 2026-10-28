"""Validate image uploads while preserving their original file contents."""
from io import BytesIO
import warnings
import logging
import time

from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 15_000
# Retain legacy field metadata for migration compatibility; forms show current formats.
UPLOAD_HELP = 'Slika se automatski sprema kao AVIF do 15 KB. Po potrebi se smanjuju kvalitet i rezolucija; animacije se spremaju kao prva slika.'


logger = logging.getLogger(__name__)
MAX_SOURCE_PIXELS = 12_000_000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_BANNER_BYTES = 150_000
BANNER_IMAGE_OPTIONS = {
    "max_bytes": MAX_BANNER_BYTES, "max_side": 1920, "prefer_webp": False, "quality": None,
}



def _encode(image, format, **options):
    output = BytesIO()
    image.save(output, format=format, **options)
    return output.getvalue()


def optimize_image(upload, max_bytes=MAX_IMAGE_BYTES, *, max_side=None, prefer_webp=False, quality=None, preserve_quality=False):
    """Validate an upload without changing its original format, bytes or dimensions.

    Legacy optimization arguments remain accepted for migration/API compatibility.
    """
    if getattr(upload, '_validated_original_image', False):
        return upload
    started = time.monotonic()
    try:
        if upload.size > MAX_UPLOAD_BYTES:
            raise ValidationError('Slika je prevelika. Najveća veličina uploada je 20 MB.')
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP', 'GIF', 'AVIF'):
                    raise ValidationError('Odaberite PNG, JPG, WebP, GIF ili AVIF sliku.')
                if source.width * source.height > MAX_SOURCE_PIXELS:
                    raise ValidationError('Slika je prevelike rezolucije. Najviše 12 megapiksela.')
                upload.content_type = Image.MIME.get(source.format, 'application/octet-stream')
                source.verify()
        upload._validated_original_image = True
        return upload
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError('Odaberite ispravnu PNG, JPG, WebP, GIF ili AVIF sliku.') from None
    finally:
        upload.seek(0)
        logger.info('image_validate original_preserved=%s elapsed_ms=%.1f',
                    getattr(upload, '_validated_original_image', False),
                    (time.monotonic() - started) * 1000)


class AVIFUploadFormField(forms.FileField):
    def __init__(self, *args, max_bytes=MAX_IMAGE_BYTES, max_side=None, prefer_webp=False, quality=None, preserve_quality=False, **kwargs):
        self.max_bytes = max_bytes
        self.max_side = max_side
        self.prefer_webp = prefer_webp
        self.quality = quality
        self.preserve_quality = preserve_quality
        super().__init__(*args, **kwargs)
        self.widget.attrs['accept'] = 'image/png,image/jpeg,image/webp,image/gif,image/avif'

    def clean(self, data, initial=None):
        value = super().clean(data, initial)
        if value and value is not initial:
            return optimize_image(value, self.max_bytes, max_side=self.max_side, prefer_webp=self.prefer_webp, quality=self.quality, preserve_quality=self.preserve_quality)
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
            'help_text': 'Originalni format, kvalitet i dimenzije ostaju sačuvani. Do 20 MB i 12 megapiksela.',
            **kwargs,
        })

    def optimization_options(self, instance=None):
        if (instance._meta.label_lower if instance is not None else self.model._meta.label_lower) == 'shop.banner':
            return dict(BANNER_IMAGE_OPTIONS)
        if (instance._meta.label_lower if instance is not None else self.model._meta.label_lower) in ('shop.product', 'shop.productimage'):
            return {'max_bytes': 30_000, 'max_side': 1600, 'prefer_webp': False,
                    'quality': 80, 'preserve_quality': False}
        return {'max_bytes': 1_000_000, 'max_side': 1024 if self.name == 'logo' else 1920,
                'prefer_webp': self.name == 'logo', 'quality': 85, 'preserve_quality': True}

    def pre_save(self, model_instance, add):
        file = getattr(model_instance, self.attname)
        if file and not file._committed:
            options = {'max_bytes': self.max_bytes, **self.optimization_options(model_instance)}
            validated = optimize_image(file.file, **options)
            setattr(model_instance, self.attname, validated)
        return super().pre_save(model_instance, add)
