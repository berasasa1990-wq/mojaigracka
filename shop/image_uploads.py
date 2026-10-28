"""Preserve source formats; fit product artwork to its storage byte budget."""
from io import BytesIO
import warnings
import logging
import time

from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from PIL import Image, ImageOps, UnidentifiedImageError
from django.core.files.base import ContentFile

MAX_IMAGE_BYTES = 15_000
# Retain legacy field metadata for migration compatibility; forms show current formats.
UPLOAD_HELP = 'Slika se automatski sprema kao AVIF do 15 KB. Po potrebi se smanjuju kvalitet i rezolucija; animacije se spremaju kao prva slika.'


logger = logging.getLogger(__name__)
MAX_SOURCE_PIXELS = 12_000_000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PRODUCT_IMAGE_BYTES = 20_000
MAX_BANNER_BYTES = 150_000
BANNER_IMAGE_OPTIONS = {
    "max_bytes": MAX_BANNER_BYTES, "max_side": 1920, "prefer_webp": False, "quality": None,
}



def _encode(image, format, **options):
    output = BytesIO()
    image.save(output, format=format, **options)
    return output.getvalue()


def _fit_product_image(upload, limit):
    """Bounded encoding in the source format; never store an oversized result."""
    started = time.monotonic()
    upload.seek(0)
    with Image.open(upload) as source:
        format = source.format
        count = getattr(source, 'n_frames', 1)
        if source.width * source.height * count > MAX_SOURCE_PIXELS:
            raise ValidationError('Animacija je prevelika za obradu. Najviše 12 megapiksela ukupno.')
        originals, durations = [], []
        loop = source.info.get('loop', 0)
        for index in range(count):
            source.seek(index)
            frame = ImageOps.exif_transpose(source).convert('RGBA' if source.has_transparency_data else 'RGB')
            frame.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            frame.info.clear()
            originals.append(frame)
            durations.append(source.info.get('duration', 100))
    frames = originals
    for attempt in range(8):
        if time.monotonic() - started > 5:
            raise ValidationError('Obrada slike traje predugo. Pokušajte s manjom izvornom slikom.')
        quality = 90 if attempt == 0 else 85
        options = {}
        if format == 'JPEG':
            options = {'quality': quality, 'optimize': False}
        elif format == 'WEBP':
            options = {'quality': quality, 'method': 0, 'alpha_quality': 100, 'exact': True}
        elif format == 'AVIF':
            options = {'quality': quality, 'speed': 10, 'max_threads': 1}
        elif format == 'PNG':
            options = {'compress_level': 6}
        if len(frames) > 1:
            options.update(save_all=True, append_images=frames[1:], duration=durations, loop=loop)
        data = _encode(frames[0], format, **options)
        if len(data) <= limit:
            result = ContentFile(data, name=upload.name)
            result.content_type = Image.MIME.get(format, 'application/octet-stream')
            result._validated_original_image = True
            return result
        # First compare two high quality settings before reducing lossy formats.
        if attempt == 0 and format in ('JPEG', 'WEBP', 'AVIF'):
            continue
        scale = min(.9, max(.2, (limit / len(data)) ** .5 * .92))
        size = tuple(max(1, int(n * scale)) for n in frames[0].size)
        frames = [frame.resize(size, Image.Resampling.LANCZOS) for frame in originals]
    raise ValidationError('Slika se ne može obraditi do 20 KB. Pokušajte s jednostavnijom slikom.')


def optimize_image(upload, max_bytes=MAX_IMAGE_BYTES, *, max_side=None, prefer_webp=False, quality=None, preserve_quality=False, max_original_bytes=None):
    """Validate originals and fit oversized product images in their source format.

    Legacy optimization arguments remain accepted for migration/API compatibility.
    """
    if (getattr(upload, '_validated_original_image', False)
            and (max_original_bytes is None or upload.size <= max_original_bytes)):
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
        if max_original_bytes is not None and upload.size > max_original_bytes:
            return _fit_product_image(upload, max_original_bytes)
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
    def __init__(self, *args, max_bytes=MAX_IMAGE_BYTES, max_side=None, prefer_webp=False, quality=None, preserve_quality=False, max_original_bytes=None, **kwargs):
        self.max_original_bytes = max_original_bytes
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
            return optimize_image(value, self.max_bytes, max_side=self.max_side, prefer_webp=self.prefer_webp, quality=self.quality, preserve_quality=self.preserve_quality, max_original_bytes=self.max_original_bytes)
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
            'help_text': ('Veća slika automatski se smanjuje na najviše 20 KB, u istom formatu. Po potrebi se smanjuju dimenzije; čuva se što bolji kvalitet.'
                          if self.optimization_options().get('max_original_bytes') else
                          'Originalni format, kvalitet i dimenzije ostaju sačuvani. Do 20 MB i 12 megapiksela.'),
            **kwargs,
        })

    def optimization_options(self, instance=None):
        if (instance._meta.label_lower if instance is not None else self.model._meta.label_lower) == 'shop.banner':
            return dict(BANNER_IMAGE_OPTIONS)
        if (instance._meta.label_lower if instance is not None else self.model._meta.label_lower) in ('shop.product', 'shop.productimage'):
            return {'max_original_bytes': MAX_PRODUCT_IMAGE_BYTES}
        return {'max_bytes': 1_000_000, 'max_side': 1024 if self.name == 'logo' else 1920,
                'prefer_webp': self.name == 'logo', 'quality': 85, 'preserve_quality': True}

    def generate_filename(self, instance, filename):
        label = instance._meta.label_lower
        if label not in ('shop.product', 'shop.productimage'):
            return super().generate_filename(instance, filename)
        import datetime
        import posixpath
        import re
        from pathlib import Path
        from django.core.files.utils import validate_file_name

        product = instance if label == 'shop.product' else instance.product
        name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', ' ', product.name)
        name = ' '.join(name.split()).strip(' .') or 'artikal'
        extension = Path(filename).suffix
        directory = datetime.datetime.now().strftime(str(self.upload_to))
        # Reserve space for storage's collision suffix within the existing field limit.
        available = self.max_length - len(directory) - len('mojaigracka.com - ') - len(extension) - 10
        basename = f'mojaigracka.com - {name[:max(1, available)].rstrip()}{extension}'
        # Keep spaces in the requested public filename; validate before storage.save().
        candidate = validate_file_name(posixpath.join(directory, basename), allow_relative_path=True)
        if self.storage.exists(candidate):
            from uuid import uuid4
            # Keep .com in the brand prefix when Django detects a name collision.
            stem = basename[:-len(extension)] if extension else basename
            candidate = posixpath.join(directory, f'{stem} - {uuid4().hex[:8]}{extension}')
        return candidate

    def pre_save(self, model_instance, add):
        file = getattr(model_instance, self.attname)
        if file and not file._committed:
            options = {'max_bytes': self.max_bytes, **self.optimization_options(model_instance)}
            validated = optimize_image(file.file, **options)
            setattr(model_instance, self.attname, validated)
        return super().pre_save(model_instance, add)
