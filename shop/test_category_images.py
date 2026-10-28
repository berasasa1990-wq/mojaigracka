from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Category


class CategoryIconTests(TestCase):
    def test_existing_large_image_is_small_and_cached(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            cache.clear()
            source = BytesIO()
            Image.effect_noise((1024, 1536), 100).convert('RGB').save(source, 'WEBP', quality=95)
            original = source.getvalue()
            category = Category.objects.create(name='Figure')
            category.image.save('large.webp', ContentFile(original), save=True)
            url = category.icon_url
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/webp')
            self.assertLessEqual(len(response.content), 28_000)
            with Image.open(BytesIO(response.content)) as icon:
                self.assertLessEqual(max(icon.size), 300)
                self.assertAlmostEqual(icon.width / icon.height, 2 / 3, places=2)
            with category.image.open('rb') as file:
                self.assertEqual(file.read(), original)
            self.assertEqual(self.client.get(url).content, response.content)
            self.assertContains(self.client.get(reverse('home')), url)

    def test_missing_image_returns_404(self):
        category = Category.objects.create(name='Bez slike')
        self.assertEqual(self.client.get(category.icon_url).status_code, 404)
