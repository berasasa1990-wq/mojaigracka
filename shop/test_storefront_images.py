from io import BytesIO
from tempfile import TemporaryDirectory
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from .models import Banner, StoreSettings


class StorefrontImageTests(TestCase):
    def test_banner_sizes_and_logo_limit(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            output = BytesIO()
            Image.effect_noise((1600, 600), 80).convert('RGB').save(output, 'PNG')
            banner = Banner.objects.create(position='offer_left', title='Ponuda', is_active=True)
            banner.image.save('responsive.png', ContentFile(output.getvalue()))
            for width, limit in ((400, 30000), (800, 65000), (1600, 130000)):
                response = self.client.get(reverse('storefront_image', args=['banner', banner.pk, width]))
                self.assertEqual(response.status_code, 200)
                self.assertLessEqual(len(response.content), limit)
                with Image.open(BytesIO(response.content)) as image:
                    self.assertLessEqual(image.width, width)
            store = StoreSettings.objects.create()
            store.logo.save('logo.png', ContentFile(output.getvalue()))
            response = self.client.get(reverse('storefront_image', args=['logo', store.pk, 440]))
            self.assertEqual(response.status_code, 200)
            self.assertLessEqual(len(response.content), 30000)
            home = self.client.get(reverse('home'))
            self.assertContains(home, 'srcset=')
            self.assertContains(home, reverse('storefront_image', args=['banner', banner.pk, 400]))

    def test_unbounded_sizes_are_rejected(self):
        self.assertEqual(self.client.get(reverse('storefront_image', args=['banner', 1, 9999])).status_code, 404)
