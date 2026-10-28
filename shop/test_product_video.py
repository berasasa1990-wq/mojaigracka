import struct
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from .product_video import validate_product_video
from .models import Product


def movie(seconds):
    def atom(kind, data):
        return struct.pack('>I4s', len(data) + 8, kind) + data
    return SimpleUploadedFile('clip.mp4', atom(b'ftyp', b'isom\0\0\0\0isom') + atom(b'moov', atom(b'mvhd', b'\0' * 12 + struct.pack('>II', 1000, seconds * 1000))), content_type='video/mp4')


class ProductVideoTests(TestCase):
    def test_duration_and_invalid_uploads(self):
        file = movie(5)
        validate_product_video(file)
        self.assertEqual(file.tell(), 0)
        for file in (movie(6), SimpleUploadedFile('fake.mp4', b'not video')):
            with self.assertRaises(ValidationError):
                validate_product_video(file)

    def test_mov_without_ftyp_is_accepted(self):
        file = movie(5)
        data = file.read()
        file = SimpleUploadedFile('clip.mov', data[20:], content_type='video/quicktime')
        validate_product_video(file)
        self.assertEqual(file.tell(), 0)

    def test_video_detail_only(self):
        product = Product.objects.create(name='Video artikal', price=10, video='products/videos/clip.mp4')
        response = self.client.get(product.get_absolute_url())
        self.assertContains(response, 'autoplay muted loop playsinline')
        self.assertContains(response, product.video.url)
        self.assertNotContains(self.client.get('/'), '<video')
