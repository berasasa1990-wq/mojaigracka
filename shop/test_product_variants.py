from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from . import image_uploads
from .forms import ProductForm
from .models import Product, ProductImage
from .product_images import PROFILES, prepare_product_image
from .test_image_uploads import upload


@override_settings(PRODUCT_IMAGE_TRY_AVIF=False)
class ProductVariantEncodingTests(SimpleTestCase):
    def test_avif_thumbnail_has_webp_fallback_and_srcset_does_not_mix_types(self):
        from types import SimpleNamespace
        from .product_images import image_sources
        storage = InMemoryStorage(base_url='https://media.example.com/')
        file = SimpleNamespace(name='products/main.webp', url='https://media.example.com/products/main.webp', storage=storage)
        manifest = {'source': file.name}
        for label, (side, _) in PROFILES.items():
            format = 'AVIF' if label == 'thumbnail' else 'WEBP'
            manifest[label] = {'name': f'products/{label}.{format.lower()}', 'width': side, 'height': side, 'format': format}
        sources = image_sources(file, manifest)
        self.assertTrue(sources['thumbnail_avif_url'].endswith('.avif'))
        self.assertTrue(sources['thumbnail_fallback_url'].endswith('.webp'))
        self.assertNotIn('.avif', sources['srcset'])

    def test_three_fixed_quality_encodes_and_soft_targets(self):
        source = upload(Image.effect_noise((1600, 1600), 70).convert('RGB'))
        with patch('shop.image_uploads._encode', wraps=image_uploads._encode) as encode:
            result = prepare_product_image(source)
        self.assertEqual(encode.call_count, 3)
        self.assertGreater(result.size, 60_000)  # Detail is kept despite the target.
        for label, (side, _) in PROFILES.items():
            item = result._product_derivatives[label]
            self.assertEqual((item['width'], item['height']), (side, side))
            self.assertEqual(item['mime'], 'image/webp')
            self.assertTrue(item['file'].name.endswith('.webp'))
            with Image.open(item['file']) as image:
                self.assertEqual(image.format, 'WEBP')
        for call in encode.call_args_list:
            self.assertEqual(call.args[1], 'WEBP')
            self.assertEqual(call.kwargs['quality'], 85)
            self.assertEqual(call.kwargs['method'], 0)

    def test_proportions_transparency_colors_and_no_upscaling(self):
        for size in ((1500, 600), (400, 1200), (40, 25)):
            with self.subTest(size=size):
                result = prepare_product_image(upload(Image.new('RGBA', size, (20, 80, 160, 120))))
                for label, (side, _) in PROFILES.items():
                    item = result._product_derivatives[label]
                    self.assertLessEqual(max(item['width'], item['height']), min(side, max(size)))
                    self.assertAlmostEqual(item['width'] / item['height'], size[0] / size[1], delta=.03)
                    with Image.open(item['file']) as image:
                        rgba = image.convert('RGBA').getpixel((0, 0))
                        self.assertEqual(rgba[3], 120)
                        for actual, expected in zip(rgba[:3], (20, 80, 160)):
                            self.assertLessEqual(abs(actual - expected), 4)

    def test_16bit_png_gradient_is_scaled_without_clipping_highlights(self):
        gradient = Image.linear_gradient('L').convert('I').point(lambda value: value * 257).convert('I;16')
        output = BytesIO()
        gradient.save(output, 'PNG')
        result = prepare_product_image(ContentFile(output.getvalue(), name='16bit.png'))
        with Image.open(result) as image:
            self.assertLess(abs(image.getpixel((128, 128))[0] - 128), 10)
            self.assertLess(image.getpixel((128, 0))[0], 10)
            self.assertGreater(image.getpixel((128, 255))[0], 245)

    def test_embedded_srgb_profile_is_applied_before_metadata_is_removed(self):
        from PIL import ImageCms
        output = BytesIO()
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.new('RGB', (900, 600), (40, 110, 190)).save(output, 'PNG', icc_profile=profile)
        result = prepare_product_image(ContentFile(output.getvalue(), name='profile.png'))
        with Image.open(result) as image:
            self.assertNotIn('icc_profile', image.info)
            for actual, expected in zip(image.getpixel((0, 0)), (40, 110, 190)):
                self.assertLessEqual(abs(actual - expected), 4)

    def test_exif_orientation_is_applied_and_metadata_removed(self):
        image = Image.new('RGB', (600, 300), 'red')
        exif = Image.Exif()
        exif[274] = 6
        exif[271] = 'PRIVATE CAMERA'
        buffer = BytesIO()
        image.save(buffer, 'JPEG', exif=exif)
        source = ContentFile(buffer.getvalue(), name='exif.jpg')
        result = prepare_product_image(source)
        self.assertEqual(result._product_derivatives['main']['width'], 300)
        self.assertEqual(result._product_derivatives['main']['height'], 600)
        for item in result._product_derivatives.values():
            with Image.open(item['file']) as saved:
                self.assertFalse(saved.getexif())
                self.assertNotIn(b'PRIVATE CAMERA', item['file'].file.getvalue())

    @override_settings(PRODUCT_IMAGE_TRY_AVIF=True, PRODUCT_IMAGE_AVIF_MAX_SECONDS=.08)
    def test_single_avif_probe_selects_only_fast_results_and_falls_back(self):
        for duration, expected in ((.01, 'AVIF'), (.2, 'WEBP')):
            clock = [0.0]
            original = image_uploads._encode
            def encode(image, format, **options):
                if format == 'AVIF':
                    clock[0] += duration
                    return b'avif-probe'
                return original(image, format, **options)
            with self.subTest(duration=duration), patch('shop.product_images.features.check', return_value=True), \
                    patch('shop.product_images.time.monotonic', side_effect=lambda: clock[0]), \
                    patch('shop.image_uploads._encode', side_effect=encode) as spy:
                result = prepare_product_image(upload())
                self.assertEqual(sum(c.args[1] == 'AVIF' for c in spy.call_args_list), 1)
                self.assertEqual(result._product_derivatives['thumbnail']['format'], expected)
                self.assertEqual(result._product_derivatives['main']['format'], 'WEBP')

    @override_settings(PRODUCT_IMAGE_TRY_AVIF=True)
    def test_avif_error_does_not_leak_details_or_block_upload(self):
        original = image_uploads._encode
        def encode(image, format, **options):
            if format == 'AVIF':
                raise OSError('secret-marker')
            return original(image, format, **options)
        with patch('shop.product_images.features.check', return_value=True), \
                patch('shop.image_uploads._encode', side_effect=encode), \
                self.assertLogs('shop.product_images', level='WARNING') as logs:
            result = prepare_product_image(upload())
        self.assertEqual(result.content_type, 'image/webp')
        self.assertNotIn('secret-marker', ' '.join(logs.output))


@override_settings(PRODUCT_IMAGE_TRY_AVIF=False)
class ProductVariantStorageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.overrides = override_settings(MEDIA_ROOT=self.temp.name)
        self.overrides.enable()
        self.addCleanup(self.overrides.disable)

    def test_form_save_encodes_once_stores_manifest_and_responsive_markup(self):
        with patch('shop.image_uploads._encode', wraps=image_uploads._encode) as encode:
            form = ProductForm({'name': 'Igračka', 'price': 10, 'is_active': 'on'},
                               {'image': upload(Image.new('RGB', (1200, 900), 'red'))})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(encode.call_count, 3)
            product = form.save()
            self.assertEqual(encode.call_count, 3)
        product.refresh_from_db()
        self.assertEqual(product.image_variants['source'], product.image.name)
        for label in PROFILES:
            meta = product.image_variants[label]
            self.assertTrue(product.image.storage.exists(meta['name']))
            self.assertEqual(meta['mime'], 'image/webp')
            self.assertEqual(product.image.storage.size(meta['name']), meta['bytes'])
        response = self.client.get(product.get_absolute_url())
        self.assertContains(response, 'srcset=')
        self.assertContains(response, 'sizes=')
        self.assertContains(response, 'fetchpriority="high"')
        self.assertNotContains(response, 'data-product-main-image loading="lazy"')
        home = self.client.get('/noviteti/')
        self.assertContains(home, product.image_card_url)
        self.assertContains(home, 'loading="lazy"')
        self.assertContains(home, product.image_srcset)

    def test_direct_field_save_and_additional_images_generate_variants(self):
        product = Product.objects.create(name='Direct', price=10)
        product.image.save('source.png', upload())
        product.refresh_from_db()
        self.assertEqual(set(product.image_variants), {'version', 'source', *PROFILES})
        extra = ProductImage.objects.create(product=product, image=upload())
        extra.refresh_from_db()
        self.assertEqual(extra.image_variants['source'], extra.image.name)
        response = self.client.get(product.get_absolute_url())
        self.assertContains(response, extra.image.storage.url(extra.image_variants['thumbnail']['name']))

    def test_update_fields_persists_manifest_without_touching_old_files(self):
        old = Product.objects.create(name='Old', price=10, image='products/old.png')
        old.image.storage.save(old.image.name, ContentFile(b'old-bytes'))
        with patch.object(old.image.storage, 'delete', wraps=old.image.storage.delete) as delete:
            old.image = upload()
            old.save(update_fields=['image'])
            old.refresh_from_db()
            self.assertEqual(old.image_variants['source'], old.image.name)
            before = list(Path(self.temp.name).rglob('*'))
            old.name = 'Updated name'
            old.save(update_fields=['name'])
            self.assertEqual(list(Path(self.temp.name).rglob('*')), before)
            delete.assert_not_called()
        self.assertEqual((Path(self.temp.name) / 'products/old.png').read_bytes(), b'old-bytes')

    def test_legacy_images_never_get_generated_or_modified_on_read(self):
        product = Product.objects.create(name='Legacy', price=10, image='products/legacy.jpg')
        with patch('shop.image_uploads._encode') as encode:
            self.assertEqual(product.image_variants, {})
            self.assertEqual(product.image_srcset, '')
            self.assertIn('/slika/', product.image_url)
            self.client.get(product.get_absolute_url())
            product.name = 'Legacy edited'
            product.save()
            encode.assert_not_called()
        self.assertEqual(product.image.name, 'products/legacy.jpg')

    def test_storage_urls_are_direct_public_cdn_without_private_storage(self):
        remote = InMemoryStorage(base_url='https://media.example.com/')
        field = Product._meta.get_field('image')
        with patch.object(field, 'storage', remote), patch.object(remote, 'delete') as delete:
            product = Product.objects.create(name='R2', price=10, image=upload(Image.new('RGB', (1200, 900), 'blue')))
            self.assertTrue(product.image_card_url.startswith('https://media.example.com/'))
            self.assertIn(' 300w', product.image_srcset)
            self.assertIn('image/webp', [item['mime'] for key, item in product.image_variants.items() if key in PROFILES])
            delete.assert_not_called()

    def test_failed_variant_upload_keeps_database_reference_and_never_deletes(self):
        remote = InMemoryStorage()
        remote.save('products/old.webp', ContentFile(b'old-object'))
        field = Product._meta.get_field('image')
        with patch.object(field, 'storage', remote):
            product = Product.objects.create(name='Existing', price=10, image='products/old.webp')
            original_save = remote.save
            count = [0]
            def fail_second(name, content, **kwargs):
                count[0] += 1
                if count[0] == 2:
                    raise OSError('network failure')
                return original_save(name, content, **kwargs)
            with patch.object(remote, 'save', side_effect=fail_second), patch.object(remote, 'delete') as delete:
                product.image = upload()
                from django.db import transaction
                from .product_images import ProductImageUploadError
                with self.assertRaises(ProductImageUploadError), transaction.atomic():
                    product.save()
                delete.assert_not_called()
            product.refresh_from_db()
            self.assertEqual(product.image.name, 'products/old.webp')
            self.assertEqual(product.image_variants, {})
            self.assertTrue(remote.exists('products/old.webp'))

    def test_panel_reports_storage_failure_without_overwriting_existing_image(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_user('variant-manager', is_staff=True))
        product = Product.objects.create(name='Existing', price=10, image='products/existing.webp')
        with patch('shop.storage.save_product_derivatives', side_effect=OSError('provider-secret')):
            response = self.client.post(f'/panel/artikli/{product.pk}/uredi/', {
                'name': 'Existing', 'price': 10, 'is_active': 'on', 'image': upload()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'postojeće slike su sačuvane')
        self.assertNotContains(response, 'provider-secret')
        product.refresh_from_db()
        self.assertEqual(product.image.name, 'products/existing.webp')
