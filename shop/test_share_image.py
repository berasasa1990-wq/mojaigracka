from io import BytesIO
from tempfile import TemporaryDirectory
from PIL import Image
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import Product
from .test_image_uploads import upload


class ProductShareImageTests(TestCase):
    def test_fitted_jpeg_and_social_metadata(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            product = Product.objects.create(name='Telefon', price=10, image=upload(Image.new('RGB', (200, 600), 'red')))
            url = reverse('product_share_image', args=[product.pk])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/jpeg')
            with Image.open(BytesIO(response.content)) as artwork:
                self.assertEqual(artwork.size, (1200, 630))
                self.assertEqual(artwork.getpixel((0, 0)), (255, 255, 255))
                self.assertGreater(artwork.getpixel((600, 315))[0], 240)
            self.assertContains(self.client.get(product.get_absolute_url()), 'http://testserver' + url)
            product.is_active = False
            product.save(update_fields=['is_active'])
            self.assertEqual(self.client.get(url).status_code, 404)
