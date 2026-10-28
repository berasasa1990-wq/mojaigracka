from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from .forms import BannerForm, BrandForm, LogoForm, ProductForm
from .image_uploads import optimize_image
from .models import Banner, Brand, Category, Product, ProductImage, StoreSettings


def upload(image=None, format='PNG'):
    image = image if image is not None else Image.new('RGBA', (300, 150), (20, 80, 160, 120))
    output = BytesIO()
    image.save(output, format=format)
    extension = 'jpg' if format == 'JPEG' else format.lower()
    return SimpleUploadedFile('example.' + extension, output.getvalue(), content_type=Image.MIME.get(format, 'application/octet-stream'))


class ImageUploadTests(TestCase):
    def test_supported_formats_preserve_original_bytes_dimensions_and_format(self):
        for format in ('PNG', 'JPEG', 'WEBP', 'GIF', 'AVIF'):
            with self.subTest(format=format):
                original = upload(Image.new('RGB', (2400, 800), 'blue'), format)
                data = original.read()
                original.seek(0)
                with patch('shop.image_uploads._encode') as encode:
                    result = optimize_image(original, max_bytes=1, max_side=100)
                encode.assert_not_called()
                self.assertEqual(result.read(), data)
                result.seek(0)
                with Image.open(result) as image:
                    self.assertEqual(image.format, format)
                    self.assertEqual(image.size, (2400, 800))

    def test_all_public_model_uploads_preserve_contents_and_unrelated_save(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            product = Product.objects.create(name='Parent', price=1)
            targets = [(Brand(name='Brand'), 'logo'), (Category(name='Category'), 'image'),
                       (product, 'image'), (ProductImage(product=product), 'image'),
                       (Banner(title='Banner', position='hero'), 'image'),
                       (StoreSettings(), 'logo')]
            for instance, field in targets:
                with self.subTest(model=type(instance).__name__):
                    original = upload()
                    data = original.read()
                    original.seek(0)
                    setattr(instance, field, original)
                    instance.save()
                    saved = getattr(instance, field)
                    self.assertTrue(saved.name.endswith('.png'))
                    with saved.open('rb') as file:
                        self.assertEqual(file.read(), data)
                    name = saved.name
                    instance.save()
                    self.assertEqual(getattr(instance, field).name, name)

    def test_forms_validate_once_without_encoding(self):
        from . import image_uploads
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            for form in [BrandForm({'name': 'Brand'}, {'logo': upload()}),
                         LogoForm({}, {'logo': upload()}),
                         ProductForm({'name': 'Product', 'price': 10, 'is_active': 'on'}, {'image': upload()}),
                         BannerForm({'position': 'hero', 'title': 'Banner'}, {'image': upload(), 'secondary_image': upload()})]:
                with patch('shop.image_uploads.Image.open', wraps=image_uploads.Image.open) as opened, \
                        patch('shop.image_uploads._encode') as encode:
                    self.assertTrue(form.is_valid(), form.errors)
                    count = opened.call_count
                    form.save()
                    self.assertEqual(opened.call_count, count)
                    encode.assert_not_called()

    def test_animation_and_transparency_are_not_modified(self):
        output = BytesIO()
        frames = [Image.new('RGB', (50, 50), color) for color in ('red', 'blue')]
        frames[0].save(output, format='GIF', save_all=True, append_images=frames[1:], duration=200, loop=0)
        original = SimpleUploadedFile('animation.gif', output.getvalue())
        self.assertEqual(optimize_image(original).read(), output.getvalue())
        result = optimize_image(upload())
        with Image.open(result) as image:
            self.assertEqual(image.getpixel((0, 0))[3], 120)

    def test_invalid_file_and_source_limits_are_form_errors(self):
        form = BrandForm({'name': 'Brand'}, {'logo': SimpleUploadedFile('fake.png', b'not an image')})
        self.assertFalse(form.is_valid())
        self.assertIn('logo', form.errors)
        with patch('shop.image_uploads.MAX_SOURCE_PIXELS', 10), self.assertRaises(ValidationError):
            optimize_image(upload())
        with patch('shop.image_uploads.MAX_UPLOAD_BYTES', 10), self.assertRaises(ValidationError):
            optimize_image(upload())

    def test_large_banner_no_longer_has_compression_budget(self):
        original = upload(Image.effect_noise((1600, 600), 70).convert('RGB'))
        self.assertGreater(original.size, 150_000)
        data = original.read()
        original.seek(0)
        form = BannerForm({'position': 'hero', 'title': 'Original'}, {'image': original})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['image'].read(), data)


    def test_product_uploads_receive_branded_filename_and_preserve_bytes(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            product = Product.objects.create(name='Hot Wheel', price=10)
            for format, extension in [('PNG', '.png'), ('JPEG', '.jpg'), ('AVIF', '.avif')]:
                original = upload(Image.new('RGB', (100, 50), 'blue'), format)
                data = original.read()
                original.seek(0)
                product.image = original
                product.save()
                self.assertEqual(product.image.name, 'products/mojaigracka.com - Hot Wheel' + extension)
                with product.image.open('rb') as stored:
                    self.assertEqual(stored.read(), data)
            extra = ProductImage.objects.create(product=product, image=upload())
            self.assertEqual(extra.image.name, 'products/gallery/mojaigracka.com - Hot Wheel.png')
            duplicate = ProductImage.objects.create(product=product, image=upload())
            self.assertNotEqual(duplicate.image.name, extra.image.name)
            self.assertTrue(duplicate.image.name.startswith('products/gallery/mojaigracka.com - Hot Wheel'))

    def test_product_filename_is_safe_and_fits_field_length(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            product = Product.objects.create(name='../Dječja / igračka\n' + 'A' * 200, price=10, image=upload())
            self.assertLessEqual(len(product.image.name), 100)
            self.assertTrue(product.image.name.startswith('products/mojaigracka.com - '))
            self.assertNotIn('..', product.image.name)
            self.assertNotIn('\n', product.image.name)


    def test_product_images_over_20kb_are_rejected_without_quality_loss(self):
        original = upload(Image.effect_noise((400, 300), 70).convert('RGB'))
        self.assertGreater(original.size, 20_000)
        form = ProductForm({'name': 'Too large', 'price': 10}, {'image': original})
        self.assertFalse(form.is_valid())
        self.assertIn('do 20 KB', str(form.errors['image']))
        extra = ProductForm({'name': 'Too large', 'price': 10}, {'additional_images': [upload(Image.effect_noise((400, 300), 70).convert('RGB'))]})
        self.assertFalse(extra.is_valid())
        self.assertIn('additional_images', extra.errors)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            product = Product.objects.create(name='Direct', price=10)
            with self.assertRaises(ValidationError):
                product.image = original
                product.save()
            with self.assertRaises(ValidationError):
                ProductImage.objects.create(product=product, image=original)

    def test_existing_large_image_is_kept_during_unrelated_edit(self):
        product = Product.objects.create(name='Existing', price=10, image='products/existing.jpg')
        product.name = 'Renamed'
        product.save()
        product.refresh_from_db()
        self.assertEqual(product.image.name, 'products/existing.jpg')
