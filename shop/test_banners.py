from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import BannerForm
from .models import Banner
from .test_image_uploads import upload


class HeroBannerTests(TestCase):
    def test_uploads_and_editable_text_render_on_home(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            form = BannerForm({
                'position': 'hero', 'title': 'Nova ponuda', 'eyebrow': 'Noviteti',
                'subtitle': 'Opis ponude', 'button_text': 'Pogledaj artikle',
                'url': '/noviteti/', 'is_active': 'on',
            }, {'image': upload(), 'secondary_image': upload()}, instance=Banner.objects.get(position='hero'))
            self.assertTrue(form.is_valid(), form.errors)
            banner = form.save()
            for image in (banner.image, banner.secondary_image):
                self.assertTrue(image.name.endswith('.webp'))
                self.assertGreater(image.size, 0)
            response = self.client.get(reverse('home'))
            for text in ('Nova ponuda', 'bera-uploaded-hero', banner.image.url):
                self.assertContains(response, text)
            self.assertNotContains(response, 'Vaš svijet.')
            banner.is_active = False
            banner.save()
            self.assertNotContains(self.client.get(reverse('home')), 'bera-hero-inner')

    def test_banner_keeps_original_aspect_ratio_and_dimensions(self):
        from PIL import Image
        artwork = Image.effect_noise((800, 300), 40).convert('RGB')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            form = BannerForm({'position': 'middle', 'title': 'Veliki banner', 'is_active': 'on'}, {'image': upload(artwork)})
            self.assertTrue(form.is_valid(), form.errors)
            banner = form.save()
            self.assertLessEqual(banner.image.size, 200_000)
            self.assertGreater(banner.image.size, 15_000)
            with Image.open(banner.image) as image:
                self.assertLessEqual(image.width, artwork.width)
                self.assertAlmostEqual(image.width / image.height, artwork.width / artwork.height, delta=.01)
            self.assertContains(self.client.get(reverse('home')), banner.image.url)

    def test_text_only_hero(self):
        form = BannerForm({'position': 'hero', 'title': 'Tekst bez slike', 'is_active': 'on'}, instance=Banner.objects.get(position='hero'))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertContains(self.client.get(reverse('home')), 'Tekst bez slike')

    def test_offer_still_requires_image(self):
        form = BannerForm({'position': 'offer_left', 'title': 'Ponuda'})
        self.assertFalse(form.is_valid())
        self.assertIn('image', form.errors)

    def test_existing_written_banner_is_available_to_edit(self):
        banner = Banner.objects.get(position='hero')
        self.assertEqual(banner.title, 'Vaš svijet.\nUz Apple.')
        self.assertEqual(banner.feature_items, ['iPhone', 'MacBook', 'AirPods', 'Apple Watch'])
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Vaš svijet.<br>Uz Apple.')

    def test_inactive_placeholder_becomes_editable_written_hero(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        Banner.objects.filter(position='hero').update(
            title='Glavni banner', is_active=False, eyebrow='', subtitle='',
            image='banners/existing.avif',
        )
        migration = import_module('shop.migrations.0021_connect_written_hero')
        migration.connect_written_hero(apps, connection.schema_editor())
        banner = Banner.objects.get(position='hero')
        self.assertTrue(banner.is_active)
        self.assertEqual(banner.title, 'Vaš svijet.\nUz Apple.')
        self.assertEqual(banner.image.name, 'banners/existing.avif')

    def test_delete_requires_staff_and_post_and_removes_home_banner(self):
        from django.contrib.auth import get_user_model
        banner = Banner.objects.get(position='hero')
        url = reverse('panel_banner_delete', args=[banner.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertTrue(Banner.objects.filter(pk=banner.pk).exists())
        staff = get_user_model().objects.create_user('banner-manager', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(Banner.objects.filter(pk=banner.pk).exists())
        self.assertRedirects(self.client.post(url), reverse('panel_section', args=['banneri']))
        self.assertFalse(Banner.objects.filter(pk=banner.pk).exists())
        self.assertNotContains(self.client.get(reverse('home')), 'bera-hero-inner')

    def test_add_another_hero_without_replacing_existing_banner(self):
        original = Banner.objects.get(position='hero')
        form = BannerForm({
            'position': 'hero', 'title': 'Drugi glavni banner',
            'subtitle': 'Drugi opis', 'button_text': 'Otvori', 'is_active': 'on',
        })
        self.assertTrue(form.is_valid(), form.errors)
        new_banner = form.save()
        response = self.client.get(reverse('home'))
        self.assertContains(response, original.title.replace('\n', '<br>'))
        self.assertContains(response, new_banner.title)
        self.assertContains(response, f'id="customHeroTitle{original.pk}"')
        self.assertContains(response, f'id="customHeroTitle{new_banner.pk}"')
        self.assertEqual(Banner.objects.filter(position='hero').count(), 2)


    def test_hero_preserves_large_artwork_and_encodes_once(self):
        from PIL import Image
        from unittest.mock import patch
        from . import image_uploads

        artwork = Image.linear_gradient('L').resize((1920, 720)).convert('RGB')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), patch(
                'shop.image_uploads._encode', wraps=image_uploads._encode) as encode:
            form = BannerForm({'position': 'hero', 'title': 'HD banner', 'is_active': 'on'},
                              {'image': upload(artwork)})
            self.assertTrue(form.is_valid(), form.errors)
            attempts = encode.call_count
            banner = form.save()
            self.assertEqual(encode.call_count, attempts)
            self.assertLessEqual(sum(call.args[1] == 'WEBP' for call in encode.call_args_list), 4)
            self.assertLessEqual(banner.image.size, 200_000)
            with banner.image.open('rb') as file, Image.open(file) as image:
                self.assertEqual(image.size, (1920, 720))

    def test_direct_hero_upload_uses_high_quality_policy(self):
        from PIL import Image

        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            banner = Banner.objects.create(position='hero', title='Direct',
                                           image=upload(Image.new('RGBA', (1920, 720), (20, 50, 80, 120))))
            with banner.image.open('rb') as file, Image.open(file) as image:
                self.assertEqual(image.size, (1920, 720))
                self.assertEqual(image.getpixel((0, 0))[3], 120)


    def test_every_banner_position_saves_both_images_as_webp(self):
        from PIL import Image

        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            for position, _ in Banner.POSITION_CHOICES:
                with self.subTest(position=position):
                    instance = Banner.objects.filter(position=position).first() or Banner(position=position)
                    form = BannerForm({'position': position, 'title': 'Banner', 'is_active': 'on'},
                                      {'image': upload(Image.new('RGB', (1600, 600), 'red')),
                                       'secondary_image': upload()}, instance=instance)
                    self.assertTrue(form.is_valid(), form.errors)
                    banner = form.save()
                    for name in ('image', 'secondary_image'):
                        stored = getattr(banner, name)
                        self.assertLessEqual(stored.size, 200_000)
                        self.assertTrue(stored.name.endswith('.webp'))
                        with stored.open('rb') as file, Image.open(file) as image:
                            self.assertEqual(image.format, 'WEBP')





    def test_large_detailed_banner_fits_200kb_webp(self):
        from PIL import Image

        artwork = Image.effect_noise((3200, 1800), 70).convert('RGB')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            banner = Banner.objects.create(position='hero', title='Large', image=upload(artwork))
            self.assertLessEqual(banner.image.size, 200_000)
            self.assertTrue(banner.image.name.endswith('.webp'))
            with banner.image.open('rb') as file, Image.open(file) as image:
                self.assertAlmostEqual(image.width / image.height, artwork.width / artwork.height, delta=.02)

    def test_portrait_landscape_and_square_banners_are_supported(self):
        from PIL import Image

        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            for size in [(3000, 400), (600, 2600), (2400, 2400)]:
                with self.subTest(size=size):
                    banner = Banner.objects.create(position='hero', title='Any ratio',
                        image=upload(Image.new('RGBA', size, (20, 50, 80, 120))))
                    self.assertLessEqual(banner.image.size, 200_000)
                    with banner.image.open('rb') as file, Image.open(file) as image:
                        self.assertAlmostEqual(image.width / image.height, size[0] / size[1], delta=.01)
                        self.assertEqual(image.getpixel((0, 0))[3], 120)


    def test_prepared_webp_preserves_bytes_dimensions_and_skips_encoding(self):
        from PIL import Image
        from unittest.mock import patch
        prepared = upload(Image.new('RGBA', (2560, 800), (20, 50, 80, 120)), format='WEBP')
        original = prepared.read()
        prepared.seek(0)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
                patch('shop.image_uploads._encode') as encode:
            form = BannerForm({'position': 'hero', 'title': 'Prepared'}, {'image': prepared})
            self.assertTrue(form.is_valid(), form.errors)
            banner = form.save()
            encode.assert_not_called()
            self.assertTrue(banner.image.name.endswith('.webp'))
            with banner.image.open('rb') as file:
                self.assertEqual(file.read(), original)
            with banner.image.open('rb') as file, Image.open(file) as image:
                self.assertEqual(image.size, (2560, 800))

    def test_banner_upload_uses_title_in_filename_and_preserves_prepared_bytes(self):
        from PIL import Image
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            source = upload(Image.new('RGB', (1920, 600), 'blue'), format='WEBP')
            original = source.read()
            source.seek(0)
            banner = Banner.objects.create(position='hero', title='Ljetna ponuda', image=source,
                                           secondary_image=upload())
            self.assertEqual(banner.image.name, 'banners/mojaigracka.com - Ljetna ponuda.webp')
            self.assertTrue(banner.secondary_image.name.startswith('banners/mojaigracka.com - Ljetna ponuda'))
            self.assertNotEqual(banner.image.name, banner.secondary_image.name)
            with banner.image.open('rb') as stored:
                self.assertEqual(stored.read(), original)

    def test_offer_banners_limit_both_images_to_150kb_in_forms_and_direct_uploads(self):
        from PIL import Image
        from unittest.mock import patch
        from . import image_uploads
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            for position in ('offer_left', 'offer_right'):
                with self.subTest(position=position), patch('shop.image_uploads._encode', wraps=image_uploads._encode) as encode:
                    artwork = Image.effect_noise((1800, 675), 50).convert('RGB')
                    form = BannerForm({'position': position, 'title': 'Side'},
                                      {'image': upload(artwork), 'secondary_image': upload(artwork)},
                                      instance=Banner.objects.filter(position=position).first())
                    self.assertTrue(form.is_valid(), form.errors)
                    attempts = encode.call_count
                    banner = form.save()
                    self.assertEqual(encode.call_count, attempts)
                    for image in (banner.image, banner.secondary_image):
                        self.assertLessEqual(image.size, 150_000)
                        with image.open('rb') as file, Image.open(file) as saved:
                            self.assertEqual(saved.format, 'WEBP')
                            self.assertAlmostEqual(saved.width / saved.height, 8 / 3, delta=.03)
                    direct = Banner.objects.get(pk=banner.pk)
                    direct.image = upload(artwork)
                    direct.save()
                    self.assertLessEqual(direct.image.size, 150_000)
                    self.assertEqual(form.fields['image'].max_original_bytes, 150_000)
                    self.assertIn('150 KB', form.fields['image'].help_text)

    def test_webp_banner_uses_more_efficient_compression_before_resizing(self):
        from PIL import Image
        from unittest.mock import patch
        from . import image_uploads
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
                patch('shop.image_uploads._encode', wraps=image_uploads._encode) as encode:
            source = upload(Image.effect_noise((1920, 720), 55).convert('RGB'), format='WEBP')
            banner = Banner.objects.create(position='hero', title='Sharp', image=source)
            self.assertLessEqual(banner.image.size, 200_000)
            self.assertGreater(encode.call_count, 0)
            self.assertEqual(encode.call_args_list[0].kwargs['quality'], 95)
            self.assertEqual(encode.call_args_list[0].kwargs['method'], 2)
            with banner.image.open('rb') as file, Image.open(file) as image:
                self.assertEqual(image.format, 'WEBP')
                self.assertAlmostEqual(image.width / image.height, 8 / 3, delta=.02)

    def test_banner_all_input_formats_convert_to_webp_without_fixed_resize(self):
        from PIL import Image
        from unittest.mock import patch
        from . import image_uploads
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            for format in ('PNG', 'JPEG', 'AVIF', 'GIF'):
                with self.subTest(format=format), patch('shop.image_uploads._encode', wraps=image_uploads._encode) as encode:
                    source = upload(Image.new('RGB', (3000, 1000), 'blue'), format=format)
                    form = BannerForm({'position': 'hero', 'title': 'Full size'}, {'image': source})
                    self.assertTrue(form.is_valid(), form.errors)
                    calls = encode.call_count
                    banner = form.save()
                    self.assertEqual(encode.call_count, calls)
                    self.assertTrue(all(call.args[1] == 'WEBP' for call in encode.call_args_list))
                    self.assertLessEqual(banner.image.size, 200_000)
                    self.assertEqual(form.cleaned_data['image'].content_type, 'image/webp')
                    with banner.image.open('rb') as file, Image.open(file) as saved:
                        self.assertEqual(saved.format, 'WEBP')
                        self.assertEqual(saved.size, (3000, 1000))
            banner = Banner.objects.create(position='hero', title='Field upload')
            banner.image.save('original.png', upload(Image.new('RGB', (3000, 1000), 'red')))
            self.assertTrue(banner.image.name.endswith('.webp'))
            with banner.image.open('rb') as file, Image.open(file) as saved:
                self.assertEqual(saved.format, 'WEBP')
                self.assertEqual(saved.size, (3000, 1000))
