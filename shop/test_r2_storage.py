from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, InMemoryStorage, storages
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from storages.backends.s3 import S3Storage

from .models import Product
from .storage import r2_configuration, public_image_storage

class StorageAliases(dict):
    @property
    def backends(self):
        return self


ENV = {
    'AWS_ACCESS_KEY_ID': 'test-only-access', 'AWS_SECRET_ACCESS_KEY': 'test-only-secret',
    'AWS_S3_ENDPOINT_URL': 'https://test-account.r2.cloudflarestorage.com',
}


class R2ConfigurationTests(SimpleTestCase):
    def test_absent_and_partial_configuration(self):
        self.assertEqual(r2_configuration({}), (None, False))
        for env in ({'AWS_ACCESS_KEY_ID': 'secret-marker'}, {'R2_ENABLED': 'true'}):
            with self.assertRaises(ImproperlyConfigured) as error:
                r2_configuration(env)
            self.assertNotIn('secret-marker', str(error.exception))

    def test_public_options_and_staging(self):
        config, enabled = r2_configuration(ENV)
        self.assertTrue(enabled)
        options = config['OPTIONS']
        self.assertEqual(options['bucket_name'], 'mojaigracka-media')
        self.assertEqual(options['region_name'], 'auto')
        self.assertEqual(options['custom_domain'], 'media.mojaigracka.com')
        self.assertIsNone(options['default_acl'])
        self.assertFalse(options['querystring_auth'])
        self.assertFalse(options['file_overwrite'])
        self.assertFalse(r2_configuration(ENV | {'R2_ENABLED': 'false'})[1])
        for name, value in [('AWS_S3_CUSTOM_DOMAIN', 'https://media.example.com'),
                            ('AWS_S3_ENDPOINT_URL', 'http://example.com'),
                            ('AWS_S3_REGION_NAME', 'us-east-1')]:
            with self.assertRaises(ImproperlyConfigured):
                r2_configuration(ENV | {name: value})

    def test_real_s3_upload_read_url_contract_without_network_or_acl(self):
        config, _ = r2_configuration(ENV)
        storage = S3Storage(**config['OPTIONS'])
        client = storage.connection.meta.client
        data = b'public-test-image'
        name = 'products/existing-name.png'
        with Stubber(client) as stub:
            stub.add_client_error('head_object', service_error_code='404', http_status_code=404,
                                  expected_params={'Bucket': 'mojaigracka-media', 'Key': name})
            stub.add_response('put_object', {'ETag': '"test"'}, {
                'Bucket': 'mojaigracka-media', 'Key': name, 'Body': ANY, 'ContentType': 'image/png',
            })
            self.assertEqual(storage.save(name, ContentFile(data)), name)
            stub.add_response('head_object', {'ContentLength': len(data)},
                              {'Bucket': 'mojaigracka-media', 'Key': name})
            stub.add_response('get_object', {
                'Body': StreamingBody(BytesIO(data), len(data)), 'ContentLength': len(data),
            }, {'Bucket': 'mojaigracka-media', 'Key': name, 'Range': ANY})
            with storage.open(name, 'rb') as uploaded:
                self.assertEqual(uploaded.read(), data)
            stub.assert_no_pending_responses()
        self.assertEqual(storage.url(name), 'https://media.mojaigracka.com/' + name)

    def test_logo_geometry_is_identical_without_local_path(self):
        from PIL import Image, ImageDraw
        from .templatetags.brand_logos import logo_geometry

        buffer = BytesIO()
        artwork = Image.new('RGB', (200, 100), 'white')
        ImageDraw.Draw(artwork).rectangle((30, 20, 160, 70), fill='black')
        artwork.save(buffer, format='PNG')
        remote = InMemoryStorage()
        remote.save('brands/logo.png', ContentFile(buffer.getvalue()))
        with TemporaryDirectory() as directory:
            local = FileSystemStorage(location=directory)
            local.save('brands/logo.png', ContentFile(buffer.getvalue()))
            class PathlessStorage:
                def open(self, name, mode):
                    return remote.open(name, mode)

                def path(self, name):
                    raise NotImplementedError

            self.assertEqual(logo_geometry(local, 'brands/logo.png', 1),
                             logo_geometry(PathlessStorage(), 'brands/logo.png', 1))

    def test_private_default_remains_filesystem(self):
        config, _ = r2_configuration(ENV)
        configs = dict(settings.STORAGES, public_images=config)
        with override_settings(STORAGES=configs):
            self.assertIsInstance(storages['default'], FileSystemStorage)
            self.assertIsInstance(public_image_storage(), S3Storage)


class R2MigrationTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='R2 test', price='10', image='products/old.avif')

    def test_dry_run_copy_idempotence_and_conflict(self):
        remote = InMemoryStorage()
        with TemporaryDirectory() as directory:
            path = Path(directory, 'products/old.avif')
            path.parent.mkdir()
            path.write_bytes(b'original')
            with patch('shop.management.commands.migrate_public_images.storages', StorageAliases(r2_images=remote)):
                call_command('migrate_public_images', source_root=directory, stdout=StringIO())
                self.assertFalse(remote.exists('products/old.avif'))
                call_command('migrate_public_images', source_root=directory, apply=True, stdout=StringIO())
                call_command('migrate_public_images', source_root=directory, apply=True, stdout=StringIO())
                path.write_bytes(b'different')
                with self.assertRaises(CommandError):
                    call_command('migrate_public_images', source_root=directory, apply=True, stdout=StringIO())
                with remote.open('products/old.avif') as file:
                    self.assertEqual(file.read(), b'original')
                self.assertTrue(path.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.image.name, 'products/old.avif')

    def test_missing_source_blocks_cutover(self):
        with TemporaryDirectory() as directory, self.assertRaises(CommandError):
            call_command('migrate_public_images', source_root=directory, stdout=StringIO())

    def test_traversal_is_rejected(self):
        self.product.image = 'products/../../private.png'
        self.product.save(update_fields=['image'])
        with TemporaryDirectory() as directory, self.assertRaises(CommandError):
            call_command('migrate_public_images', source_root=directory, stdout=StringIO())

    @override_settings(R2_IMAGES_ENABLED=True)
    def test_legacy_media_url_redirects_and_private_path_is_not_exposed(self):
        config, _ = r2_configuration(ENV)
        with override_settings(STORAGES=dict(settings.STORAGES, public_images=config)):
            response = self.client.get('/media/products/old.avif')
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response['Location'], 'https://media.mojaigracka.com/products/old.avif')
            self.assertEqual(self.client.get('/media/private/test.png').status_code, 404)


class R2ProbeTests(SimpleTestCase):
    def test_probe_upload_read_and_anonymous_get(self):
        from urllib.parse import urlsplit

        remote = InMemoryStorage()
        remote.custom_domain = 'media.mojaigracka.com'

        class PublicResponse(BytesIO):
            status = 200

        def public_get(url, timeout):
            name = urlsplit(url).path.lstrip('/')
            with remote.open(name, 'rb') as image:
                return PublicResponse(image.read())

        output = StringIO()
        with patch('shop.management.commands.check_r2_images.storages', StorageAliases(r2_images=remote)), \
                patch.object(remote, 'url', side_effect=lambda name: 'https://media.mojaigracka.com/' + name), \
                patch('shop.management.commands.check_r2_images.urlopen', side_effect=public_get):
            call_command('check_r2_images', upload=True, stdout=output)
        self.assertIn('anonymous public GET: OK', output.getvalue())
        self.assertEqual(len(remote.listdir('products/_checks')[1]), 1)

    def test_provider_errors_do_not_expose_credentials(self):
        remote = InMemoryStorage()
        with patch('shop.management.commands.check_r2_images.storages', StorageAliases(r2_images=remote)), \
                patch.object(remote, 'save', side_effect=RuntimeError('secret-marker')):
            with self.assertRaises(CommandError) as error:
                call_command('check_r2_images', upload=True, stdout=StringIO())
        self.assertNotIn('secret-marker', str(error.exception))


@override_settings(R2_IMAGES_ENABLED=True)
class PublicImageFallbackTests(TestCase):
    def setUp(self):
        self.remote = InMemoryStorage()
        self.remote.save('products/example.avif', ContentFile(b'avif-artwork'))

    def test_proxy_streams_saved_object_with_image_type_instead_of_redirect(self):
        with patch('shop.storage.public_image_storage', return_value=self.remote):
            response = self.client.get('/media/products/example.avif?proxy=1')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/avif')
            self.assertNotIn('Location', response)
            self.assertEqual(b''.join(response.streaming_content), b'avif-artwork')
            self.assertEqual(response['Cache-Control'], 'public, max-age=3600')
            response.close()

    def test_proxy_rejects_private_traversal_and_non_image_paths(self):
        self.remote.save('private/key.png', ContentFile(b'private'))
        with patch('shop.storage.public_image_storage', return_value=self.remote) as storage:
            for url in ['/media/private/key.png?proxy=1', '/media/products/../private/key.png?proxy=1',
                        '/media/products/key.txt?proxy=1']:
                self.assertEqual(self.client.get(url).status_code, 404)
            storage.assert_not_called()

    def test_missing_object_is_404_and_provider_failure_is_not_cached(self):
        from botocore.exceptions import ClientError
        with patch('shop.storage.public_image_storage', return_value=self.remote):
            self.assertEqual(self.client.get('/media/products/missing.png?proxy=1').status_code, 404)
        error = ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'secret-marker'}}, 'GetObject')
        with patch('shop.storage.public_image_storage') as storage:
            storage.return_value.open.side_effect = error
            with self.assertLogs('shop.media_views', level='WARNING') as logs:
                response = self.client.get('/media/products/example.png?proxy=1')
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertNotIn('secret-marker', ' '.join(logs.output))
        self.assertNotIn(b'secret-marker', response.content)

    def test_header_exposes_configured_domain_only_for_image_retry(self):
        self.remote.custom_domain = 'media.example.com'
        with patch('shop.storage.public_image_storage', return_value=self.remote):
            self.assertContains(self.client.get('/'), 'data-public-image-domain="media.example.com"')
