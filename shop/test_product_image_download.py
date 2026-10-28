from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import unquote

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Product, ProductImage


class ProductImageDownloadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.directory.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.product = Product.objects.create(name='Hot Wheel', price=10)
        self.url = reverse('product_image_download', args=[self.product.pk])

    def save_image(self, format='PNG', name='products/original.png'):
        output = BytesIO()
        Image.new('RGBA', (240, 120), (30, 100, 200, 120)).save(output, format=format)
        data = output.getvalue()
        saved = self.product.image.storage.save(name, ContentFile(data))
        Product.objects.filter(pk=self.product.pk).update(image=saved)
        self.product.refresh_from_db()
        return data

    def test_download_preserves_png_with_product_filename_and_alpha(self):
        self.save_image()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['Content-Disposition'], 'inline; filename="mojaigracka.com - Hot Wheel.png"')
        with Image.open(BytesIO(b''.join(response.streaming_content))) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertEqual(image.size, (240, 120))
            self.assertEqual(image.getpixel((0, 0))[3], 120)
        self.assertContains(self.client.get(self.product.get_absolute_url()), self.url)
        self.assertNotContains(self.client.get(self.product.get_absolute_url()), 'Preuzmi sliku · AVIF')

    def test_existing_avif_is_downloaded_without_reencoding(self):
        original = self.save_image('AVIF', 'products/prepared.avif')
        with patch('PIL.Image.Image.save') as encode:
            self.assertEqual(b''.join(self.client.get(self.url).streaming_content), original)
            encode.assert_not_called()

    def test_original_file_is_streamed_without_decoding_or_conversion(self):
        original = self.save_image()
        with patch('PIL.Image.open') as opened, patch('PIL.Image.Image.save') as encode:
            response = self.client.get(self.url)
            self.assertEqual(b''.join(response.streaming_content), original)
            opened.assert_not_called()
            encode.assert_not_called()

    def test_additional_image_is_allowed_but_arbitrary_paths_are_rejected(self):
        self.save_image()
        ProductImage.objects.create(product=self.product, image=self.product.image.name)
        self.assertEqual(self.client.get(self.url, {'image': self.product.image.name}).status_code, 200)
        for name in ['private/secret.png', 'products/not-owned.png', '../secret.png']:
            self.assertEqual(self.client.get(self.url, {'image': name}).status_code, 404)

    def test_unicode_filename_is_safe_and_inactive_product_is_not_public(self):
        self.save_image()
        Product.objects.filter(pk=self.product.pk).update(name='Dječja / igračka\nTest')
        header = unquote(self.client.get(self.url)['Content-Disposition'])
        self.assertIn('mojaigracka.com - Dječja igračka Test.png', header)
        self.assertNotIn('\n', header)
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_missing_image_is_404(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
