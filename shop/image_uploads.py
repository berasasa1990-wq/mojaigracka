"""Upload validation, legacy banner sizing and bounded product derivatives."""
from io import BytesIO
import warnings
import logging
import time

from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.fields.files import FieldFile
from PIL import Image, ImageOps, UnidentifiedImageError
from django.core.files.base import ContentFile

MAX_IMAGE_BYTES = 15_000
# Retain legacy field metadata for migration compatibility; forms show current formats.
UPLOAD_HELP = 'Slika se automatski sprema kao AVIF do 15 KB. Po potrebi se smanjuju kvalitet i rezolucija; animacije se spremaju kao prva slika.'


logger = logging.getLogger(__name__)
MAX_SOURCE_PIXELS = 12_000_000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_BANNER_BYTES = 200_000
BANNER_IMAGE_OPTIONS = {
    "max_original_bytes": MAX_BANNER_BYTES, "max_side": None, "quality": 95, "banner_webp": True,
}

def banner_image_options(position=None):
    options = dict(BANNER_IMAGE_OPTIONS)
    if position in ('offer_left', 'offer_right'):
        options.update(max_original_bytes=150_000)
    return options


def _encode(image, format, **options):
    output = BytesIO()
    image.save(output, format=format, **options)
    return output.getvalue()


def _fit_product_image(upload, limit, *, max_side=1600, quality=90, force_webp=False):
    """Bounded encoding in the source format; never store an oversized result."""
    started = time.monotonic()
    upload.seek(0)
    with Image.open(upload) as source:
        format = 'WEBP' if force_webp else source.format
        count = getattr(source, 'n_frames', 1)
        if source.width * source.height * count > MAX_SOURCE_PIXELS:
            raise ValidationError('Animacija je prevelika za obradu. Najviše 12 megapiksela ukupno.')
        originals, durations = [], []
        loop = source.info.get('loop', 0)
        for index in range(count):
            source.seek(index)
            frame = ImageOps.exif_transpose(source).convert('RGBA' if source.has_transparency_data else 'RGB')
            if max_side:
                frame.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            frame.info.clear()
            originals.append(frame)
            durations.append(source.info.get('duration', 100))
    frames = originals
    for attempt in range(8):
        if time.monotonic() - started > 5:
            raise ValidationError('Obrada slike traje predugo. Pokušajte s manjom izvornom slikom.')
        attempt_quality = (max(85, quality - 5 * min(attempt, 2)) if force_webp
                           else quality if attempt == 0 else max(1, quality - 5))
        options = {}
        if format == 'JPEG':
            options = {'quality': attempt_quality, 'optimize': True}
        elif format == 'WEBP':
            options = {'quality': attempt_quality, 'method': 2, 'alpha_quality': 100, 'exact': True}
        elif format == 'AVIF':
            options = {'quality': attempt_quality, 'speed': 10, 'max_threads': 1}
        elif format == 'PNG':
            options = {'compress_level': 9}
        if len(frames) > 1:
            options.update(save_all=True, append_images=frames[1:], duration=durations, loop=loop)
        data = _encode(frames[0], format, **options)
        if len(data) <= limit:
            from pathlib import Path
            name = str(Path(upload.name).with_suffix('.webp')) if force_webp else upload.name
            result = ContentFile(data, name=name)
            result.content_type = Image.MIME.get(format, 'application/octet-stream')
            result._validated_original_image = True
            result._banner_webp = force_webp
            return result
        # First compare two high quality settings before reducing lossy formats.
        if ((force_webp and attempt < 2)
                or (not force_webp and attempt == 0 and format in ('JPEG', 'WEBP', 'AVIF'))):
            continue
        scale = min(.97, max(.2, (limit / len(data)) ** .5 * .98))
        size = tuple(max(1, int(n * scale)) for n in frames[0].size)
        frames = [frame.resize(size, Image.Resampling.LANCZOS) for frame in originals]
    raise ValidationError(f'Slika se ne može obraditi do {limit // 1000} KB. Pokušajte s jednostavnijom slikom.')


def optimize_image(upload, max_bytes=MAX_IMAGE_BYTES, *, max_side=None, prefer_webp=False, quality=None, preserve_quality=False, max_original_bytes=None, product_variants=False, banner_webp=False):
    """Validate originals and fit oversized product images in their source format.

    Legacy optimization arguments remain accepted for migration/API compatibility.
    """
    if product_variants:
        from .product_images import prepare_product_image
        return prepare_product_image(upload)
    if (getattr(upload, '_validated_original_image', False)
            and (not banner_webp or getattr(upload, '_banner_webp', False))
            and (max_original_bytes is None or upload.size <= max_original_bytes)):
        return upload
    started = time.monotonic()
    try:
        if upload.size > MAX_UPLOAD_BYTES:
            raise ValidationError('Slika je prevelika. Najveća veličina uploada je 20 MB.')
        upload.seek(0)
        source_format = None
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP', 'GIF', 'AVIF'):
                    raise ValidationError('Odaberite PNG, JPG, WebP, GIF ili AVIF sliku.')
                if source.width * source.height > MAX_SOURCE_PIXELS:
                    raise ValidationError('Slika je prevelike rezolucije. Najviše 12 megapiksela.')
                source_format = source.format
                upload.content_type = Image.MIME.get(source.format, 'application/octet-stream')
                source.verify()
        if max_original_bytes is not None and (upload.size > max_original_bytes or (banner_webp and source_format != 'WEBP')):
            return _fit_product_image(upload, max_original_bytes,
                                      max_side=max_side if banner_webp else max_side or 1600,
                                      quality=quality or 90, force_webp=banner_webp)
        upload._banner_webp = banner_webp

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
    def __init__(self, *args, max_bytes=MAX_IMAGE_BYTES, max_side=None, prefer_webp=False, quality=None, preserve_quality=False, max_original_bytes=None, product_variants=False, banner_webp=False, **kwargs):
        self.banner_webp = banner_webp
        self.product_variants = product_variants
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
            return optimize_image(value, self.max_bytes, max_side=self.max_side, prefer_webp=self.prefer_webp, quality=self.quality, preserve_quality=self.preserve_quality, max_original_bytes=self.max_original_bytes, product_variants=self.product_variants, banner_webp=self.banner_webp)
        return value


class ProductVariantFieldFile(FieldFile):
    def save(self, name, content, save=True):
        if not getattr(content, 'name', None):
            content.name = name
        if self.instance._meta.label_lower == 'shop.banner':
            prepared = optimize_image(content, **self.field.optimization_options(self.instance))
            return super().save(prepared.name, prepared, save=save)
        if self.instance._meta.label_lower not in ('shop.product', 'shop.productimage'):
            return super().save(name, content, save=save)
        from .product_images import prepare_product_image
        from pathlib import PurePosixPath
        import posixpath
        prepared = prepare_product_image(content)
        self.instance._image_variant_token = prepared._product_upload_id
        store_started = time.monotonic()
        stored_count = 0
        try:
            main_key = self.field.generate_filename(self.instance, prepared.name)
            path = PurePosixPath(main_key)
            files = {}
            for label, item in prepared._product_derivatives.items():
                suffix = PurePosixPath(item['file'].name).suffix
                key = main_key if label == 'main' else posixpath.join(
                    str(path.parent), 'variants', path.stem + '-' + label + suffix)
                files[label] = (key, item['file'])
            from .storage import save_product_derivatives
            from botocore.exceptions import BotoCoreError, ClientError
            from .product_images import ProductImageUploadError
            try:
                stored = save_product_derivatives(self.storage, files)
            except (OSError, BotoCoreError, ClientError):
                logger.warning('product_image_store storage_unavailable')
                raise ProductImageUploadError('Slike trenutno nije moguće poslati u storage. Pokušajte ponovo; postojeće slike su sačuvane.') from None
            stored_count = len(stored)
            manifest = {'version': 1, 'source': stored['main']}
            for label, item in prepared._product_derivatives.items():
                manifest[label] = {key: value for key, value in item.items() if key != 'file'}
                manifest[label]['name'] = stored[label]
            self.name = stored['main']
            self._set_instance_attribute(self.name, prepared)
            self._committed = True
            self.instance.image_variants = manifest
        finally:
            logger.info('product_image_store files=%d elapsed_ms=%.1f', stored_count,
                        (time.monotonic() - store_started) * 1000)
            del self.instance._image_variant_token
        if save:
            self.instance.save()


class AVIFFileField(models.FileField):
    attr_class = ProductVariantFieldFile

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
            'help_text': ('Automatski thumbnail 300 px, kartica 500 px i glavna 800 px. Ciljne KB veličine su okvirne; kvalitet ima prednost.'
                          if self.optimization_options().get('product_variants') else f'Veća slika automatski se smanjuje na najviše {self.optimization_options().get("max_original_bytes", 0) // 1000} KB, u istom formatu. Po potrebi se smanjuju dimenzije; čuva se što bolji kvalitet.'
                          if self.optimization_options().get('max_original_bytes') else
                          'Originalni format, kvalitet i dimenzije ostaju sačuvani. Do 20 MB i 12 megapiksela.'),
            **kwargs,
        })

    def optimization_options(self, instance=None):
        if (instance._meta.label_lower if instance is not None else self.model._meta.label_lower) == 'shop.banner':
            return banner_image_options(getattr(instance, 'position', None))
        if (instance._meta.label_lower if instance is not None else self.model._meta.label_lower) in ('shop.product', 'shop.productimage'):
            return {'product_variants': True}
        return {'max_bytes': 1_000_000, 'max_side': 1024 if self.name == 'logo' else 1920,
                'prefer_webp': self.name == 'logo', 'quality': 85, 'preserve_quality': True}

    def generate_filename(self, instance, filename):
        label = instance._meta.label_lower
        if label not in ('shop.product', 'shop.productimage', 'shop.banner'):
            return super().generate_filename(instance, filename)
        import datetime
        import posixpath
        import re
        from pathlib import Path
        from django.core.files.utils import validate_file_name

        title = instance.title if label == 'shop.banner' else (instance.name if label == 'shop.product' else instance.product.name)
        name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', ' ', title)
        name = ' '.join(name.split()).strip(' .') or ('banner' if label == 'shop.banner' else 'artikal')
        extension = Path(filename).suffix
        directory = datetime.datetime.now().strftime(str(self.upload_to))
        # Reserve space for storage's collision suffix within the existing field limit.
        available = self.max_length - len(directory) - len('mojaigracka.com - ') - len(extension) - 10
        token = getattr(instance, '_image_variant_token', '')
        if token:
            available -= len(token) + 3
        basename = f'mojaigracka.com - {name[:max(1, available)].rstrip()}'
        if token:
            basename += f' - {token}'
        basename += extension
        # Keep spaces in the requested public filename; validate before storage.save().
        candidate = validate_file_name(posixpath.join(directory, basename), allow_relative_path=True)
        if not token and self.storage.exists(candidate):
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
        result = super().pre_save(model_instance, add)
        if model_instance._meta.label_lower in ('shop.product', 'shop.productimage') and not result:
            model_instance.image_variants = {}
        return result
