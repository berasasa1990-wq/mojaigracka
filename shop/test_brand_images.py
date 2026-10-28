from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Brand


class BrandLogoImageTests(TestCase):
    def test_existing_large_image_is_small_and_cached(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            cache.clear()
            source = BytesIO()
            Image.effect_noise((1024, 1536), 100).convert('RGB').save(source, 'WEBP', quality=95)
            original = source.getvalue()
            category = Brand.objects.create(name='Figure')
            category.logo.save('large.webp', ContentFile(original), save=True)
            url = category.optimized_logo_url
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/webp')
            self.assertLessEqual(len(response.content), 30_000)
            with Image.open(BytesIO(response.content)) as icon:
                self.assertLessEqual(max(icon.size), 400)
                self.assertAlmostEqual(icon.width / icon.height, 2 / 3, places=2)
            with category.logo.open('rb') as file:
                self.assertEqual(file.read(), original)
            self.assertEqual(self.client.get(url).content, response.content)
            from .templatetags.brand_logos import brand_logo
            self.assertIn(url.replace('&', '&amp;'), str(brand_logo(category)))

    def test_missing_image_returns_404(self):
        category = Brand.objects.create(name='Bez slike')
        self.assertEqual(self.client.get(category.optimized_logo_url).status_code, 404)
