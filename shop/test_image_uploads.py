from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from unittest.mock import patch
from django.contrib.auth import get_user_model
from . import image_uploads

from .forms import BrandForm, LogoForm, ProductForm
from .image_uploads import MAX_IMAGE_BYTES, optimize_image
from .models import Banner, Brand, Category, Product, StoreSettings


def upload(image=None, format='PNG'):
    image = image if image is not None else Image.new('RGBA', (300, 150), (20, 80, 160, 120))
    buffer = BytesIO()
    image.save(buffer, format=format)
    return SimpleUploadedFile('example.' + format.lower(), buffer.getvalue(), content_type='image/' + format.lower())


class ImageUploadTests(TestCase):
    def assert_optimized(self, file):
        self.assertTrue(file.name.endswith(('.avif', '.webp', '.png')))
        self.assertLessEqual(file.size, MAX_IMAGE_BYTES)
        file.seek(0)
        with Image.open(file) as image:
            self.assertEqual({'.avif': 'AVIF', '.webp': 'WEBP', '.png': 'PNG'}[Path(file.name).suffix], image.format)
            image.load()

    def test_transparency_and_proportions(self):
        result = optimize_image(upload())
        self.assert_optimized(result)
        result.seek(0)
        with Image.open(result) as image:
            self.assertEqual(image.size, (300, 150))
            self.assertEqual(image.mode, 'RGBA')
            self.assertLess(image.getpixel((0, 0))[3], 255)

    def test_noisy_image_obeys_hard_size_limit(self):
        image = Image.effect_noise((1800, 1200), 100).convert('RGB')
        self.assert_optimized(optimize_image(upload(image)))

    def test_all_model_uploads_and_unrelated_edits(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            items = [
                (Brand(name='Test'), 'logo'),
                (Category(name='Test'), 'image'),
                (Product(name='Test', price='10'), 'image'),
                (Banner(title='Test', position='offer_left'), 'image'),
                (StoreSettings(), 'logo'),
            ]
            for instance, field in items:
                with self.subTest(model=type(instance).__name__):
                    setattr(instance, field, upload())
                    instance.save()
                    file = getattr(instance, field)
                    self.assert_optimized(file)
                    name = file.name
                    file.close()
                    instance.save()
                    self.assertEqual(getattr(instance, field).name, name)

    def test_forms_convert_uploads_and_accept_avif(self):
        for form in (BrandForm({'name': 'Test'}, {'logo': upload()}), LogoForm({}, {'logo': upload()})):
            self.assertTrue(form.is_valid(), form.errors)
            self.assert_optimized(form.cleaned_data['logo'])
        form = LogoForm({}, {'logo': upload(format='AVIF')})
        self.assertTrue(form.is_valid(), form.errors)
        self.assert_optimized(form.cleaned_data['logo'])

    def test_invalid_file_is_a_form_error(self):
        form = BrandForm({'name': 'Test'}, {'logo': SimpleUploadedFile('fake.png', b'not an image')})
        self.assertFalse(form.is_valid())
        self.assertIn('logo', form.errors)
        with self.assertRaises(ValidationError):
            optimize_image(SimpleUploadedFile('fake.avif', b'not an image'))


    def test_logo_post_is_processed_once_and_preserves_alpha(self):
        self.client.force_login(get_user_model().objects.create_user('upload-manager', is_staff=True))
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
                patch('shop.image_uploads._encode', wraps=image_uploads._encode) as encode:
            response = self.client.post('/panel/logo/', {'logo': upload()})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(encode.call_count, 1)
            self.assertEqual(encode.call_args.args[1], 'PNG')
            stored = StoreSettings.objects.get(pk=1).logo
            self.assertTrue(stored.name.endswith('.png'))
            with stored.open('rb') as file, Image.open(file) as image:
                self.assertEqual(image.mode, 'RGBA')
                self.assertEqual(image.getpixel((0, 0))[3], 120)

    def test_product_form_save_uses_fast_single_avif_and_no_second_encoding(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
                patch('shop.image_uploads._encode', wraps=image_uploads._encode) as encode:
            form = ProductForm({'name': 'Slika artikla', 'price': '10', 'stock': '1',
                                'is_active': 'on'}, {'image': upload(Image.new('RGB', (1400, 900), 'red'))})
            self.assertTrue(form.is_valid(), form.errors)
            attempts_before_save = encode.call_count
            image = form.cleaned_data['image']
            self.assertEqual(image.content_type, 'image/avif')
            product = form.save()
            self.assertEqual(encode.call_count, attempts_before_save)
            self.assertEqual(attempts_before_save, 1)
            self.assertEqual(encode.call_args.kwargs['speed'], 10)
            self.assertEqual(encode.call_args.kwargs['max_threads'], 1)
            with product.image.open('rb') as file, Image.open(file) as image:
                self.assertLessEqual(max(image.size), 960)

    def test_avif_error_falls_back_with_correct_extension_mime_and_bounded_work(self):
        original = image_uploads._encode

        def encode(image, format, **options):
            if format == 'AVIF':
                raise OSError('do-not-log-this-secret')
            return original(image, format, **options)

        source = upload(Image.effect_noise((900, 600), 100).convert('RGB'))
        with patch('shop.image_uploads._encode', side_effect=encode) as spy, \
                self.assertLogs('shop.image_uploads', level='INFO') as logs:
            result = optimize_image(source)
        self.assertLessEqual(result.size, MAX_IMAGE_BYTES)
        self.assertTrue(result.name.endswith('.webp'))
        self.assertEqual(result.content_type, 'image/webp')
        self.assertEqual(sum(call.args[1] == 'AVIF' for call in spy.call_args_list), 1)
        self.assertLessEqual(spy.call_count, 1 + image_uploads.MAX_FALLBACK_ATTEMPTS)
        self.assertIn('elapsed_ms=', ' '.join(logs.output))
        self.assertNotIn('do-not-log-this-secret', ' '.join(logs.output))
        self.assertEqual(source.tell(), 0)

    def test_unavailable_encoders_use_png_and_keep_transparency(self):
        with patch('shop.image_uploads.features.check', return_value=False):
            result = optimize_image(upload())
        self.assertTrue(result.name.endswith('.png'))
        self.assertEqual(result.content_type, 'image/png')
        with Image.open(result) as image:
            self.assertEqual(image.getpixel((0, 0))[3], 120)

    def test_webp_failure_falls_back_to_png(self):
        original = image_uploads._encode

        def encode(image, format, **options):
            if format == 'WEBP':
                raise RuntimeError('encoder unavailable')
            return original(image, format, **options)

        with patch('shop.image_uploads._encode', side_effect=encode):
            result = optimize_image(upload())
        self.assertTrue(result.name.endswith('.png'))
        self.assertEqual(result.content_type, 'image/png')

    def test_pixel_limit_is_rejected_before_decoding(self):
        with patch('shop.image_uploads.MAX_SOURCE_PIXELS', 10):
            form = LogoForm({}, {'logo': upload()})
            self.assertFalse(form.is_valid())
            self.assertIn('logo', form.errors)

    def test_same_optimized_content_is_reused_without_opening_or_encoding(self):
        result = optimize_image(upload())
        with patch('shop.image_uploads.Image.open') as opened, patch('shop.image_uploads._encode') as encode:
            self.assertIs(optimize_image(result), result)
        opened.assert_not_called()
        encode.assert_not_called()
