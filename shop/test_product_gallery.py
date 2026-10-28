from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from django.urls import reverse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .forms import ProductForm
from .models import Product, ProductImage
from .test_image_uploads import upload
from . import image_uploads


class ProductGalleryTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.client.force_login(get_user_model().objects.create_user('gallery-manager', is_staff=True))
        self.product = Product.objects.create(name='Gallery', price=10, image=upload())

    def image_url(self, photo):
        return reverse('product_image_download', args=[self.product.pk]) + '?' + urlencode({'image': photo.image.name})

    def data(self):
        return {'name': 'Gallery', 'price': '10', 'stock': '1', 'is_active': 'on'}

    def test_panel_uploads_multiple_images_and_displays_vertical_gallery(self):
        original = self.product.image.name
        with patch('shop.image_uploads._encode', wraps=image_uploads._encode) as encode:
            response = self.client.post(f'/panel/artikli/{self.product.pk}/uredi/',
                                        {**self.data(), 'additional_images': [upload(), upload()]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(encode.call_count, 0)  # Form results are not re-encoded by model.
        self.product.refresh_from_db()
        self.assertEqual(self.product.image.name, original)
        photos = list(self.product.additional_images.all())
        self.assertEqual([p.position for p in photos], [0, 1])
        for photo in photos:
            self.assertTrue(photo.image.name.startswith('products/gallery/'))
            self.assertGreater(photo.image.size, 0)
        response = self.client.get(self.product.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="product-thumbnails"')
        self.assertContains(response, 'data-product-image=', count=3)
        for photo in photos:
            self.assertContains(response, self.image_url(photo))
        self.assertContains(self.client.get(f'/panel/artikli/{self.product.pk}/uredi/'), 'Postojeće dodatne slike')

    def test_empty_edit_preserves_images_and_new_upload_appends(self):
        photo = ProductImage.objects.create(product=self.product, image=upload(), position=4)
        self.client.post(f'/panel/artikli/{self.product.pk}/uredi/', self.data())
        self.assertTrue(ProductImage.objects.filter(pk=photo.pk).exists())
        self.client.post(f'/panel/artikli/{self.product.pk}/uredi/',
                         {**self.data(), 'additional_images': [upload()]})
        self.assertEqual(list(self.product.additional_images.values_list('position', flat=True)), [4, 5])

    def test_invalid_one_of_multiple_files_saves_nothing(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.client.post(f'/panel/artikli/{self.product.pk}/uredi/', {
            **self.data(), 'additional_images': [upload(), SimpleUploadedFile('bad.png', b'invalid')],
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('additional_images', response.context['edit_form'].errors)
        self.assertFalse(self.product.additional_images.exists())

    def test_limits_batch_and_supports_new_product_commit_false(self):
        form = ProductForm(self.data(), {'additional_images': [upload() for _ in range(7)]})
        self.assertFalse(form.is_valid())
        form = ProductForm(self.data(), {'additional_images': [upload()]})
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save(commit=False)
        self.assertIsNone(product.pk)
        product.save()
        form.save_m2m()
        self.assertEqual(product.additional_images.count(), 1)

    def test_gallery_without_primary_image_and_primary_only_product(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertNotContains(response, 'class="product-thumbnails"')
        self.product.image = ''
        self.product.save(update_fields=['image'])
        photo = ProductImage.objects.create(product=self.product, image=upload())
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, 'data-product-main-image')
        self.assertContains(response, self.image_url(photo))
        self.assertContains(response, 'id="productZoomDialog"')

    def test_anonymous_cannot_upload(self):
        self.client.logout()
        response = self.client.post(f'/panel/artikli/{self.product.pk}/uredi/',
                                    {**self.data(), 'additional_images': [upload()]})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.product.additional_images.exists())


    def test_remove_one_keeps_primary_and_other_photos(self):
        first = ProductImage.objects.create(product=self.product, image=upload())
        second = ProductImage.objects.create(product=self.product, image=upload())
        primary = self.product.image.name
        response = self.client.post(f'/panel/artikli/{self.product.pk}/uredi/',
                                    {**self.data(), 'remove_images': [str(first.pk)]})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProductImage.objects.filter(pk=first.pk).exists())
        self.assertTrue(ProductImage.objects.filter(pk=second.pk).exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.image.name, primary)
        page = self.client.get(self.product.get_absolute_url())
        self.assertNotContains(page, self.image_url(first))
        self.assertContains(page, self.image_url(second))

    def test_foreign_image_cannot_be_deleted(self):
        other = Product.objects.create(name='Other', price=10)
        photo = ProductImage.objects.create(product=other, image=upload())
        response = self.client.post(f'/panel/artikli/{self.product.pk}/uredi/',
                                    {**self.data(), 'remove_images': [str(photo.pk)]})
        self.assertEqual(response.status_code, 200)
        self.assertIn('remove_images', response.context['edit_form'].errors)
        self.assertTrue(ProductImage.objects.filter(pk=photo.pk).exists())

    def test_invalid_form_does_not_delete_selected_image(self):
        photo = ProductImage.objects.create(product=self.product, image=upload())
        response = self.client.post(f'/panel/artikli/{self.product.pk}/uredi/',
                                    {**self.data(), 'price': '-1', 'remove_images': [str(photo.pk)]})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ProductImage.objects.filter(pk=photo.pk).exists())
