from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

from django.db import connection
from django.http import HttpResponse
from django.test import TestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from PIL import Image

from bera_control.models import ModuleSwitch
from bera_control.services import local_allows
from shop.request_cache import RequestReadCacheMiddleware
from shop.templatetags.brand_logos import brand_logo


class RequestReadCacheTests(TestCase):
    def test_repeated_checks_use_one_query_and_next_request_sees_changes(self):
        def view(request):
            with self.assertNumQueries(1):
                for _ in range(40):
                    self.assertTrue(local_allows('wms'))
            return HttpResponse('ok')
        middleware = RequestReadCacheMiddleware(view)
        middleware(RequestFactory().get('/'))
        ModuleSwitch.objects.update_or_create(code='wms', defaults={'enabled': False})
        middleware = RequestReadCacheMiddleware(lambda r: HttpResponse(str(local_allows('wms'))))
        self.assertEqual(middleware(RequestFactory().get('/')).content, b'False')

    def test_post_reads_see_writes_and_exception_clears_context(self):
        def view(request):
            self.assertTrue(local_allows('wms'))
            ModuleSwitch.objects.update_or_create(code='wms', defaults={'enabled': False})
            self.assertFalse(local_allows('wms'))
            raise RuntimeError('test cleanup')
        with self.assertRaises(RuntimeError):
            RequestReadCacheMiddleware(view)(RequestFactory().post('/'))
        ModuleSwitch.objects.filter(code='wms').update(enabled=True)
        self.assertTrue(local_allows('wms'))

    def test_home_checks_module_once_for_many_products(self):
        from shop.models import Product
        Product.objects.bulk_create([Product(name=f'Item {i}', price=10, is_active=True,
                                            is_featured=True) for i in range(40)])
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        checks = [q['sql'] for q in queries if 'bera_control_moduleswitch' in q['sql'] and "'wms'" in q['sql']]
        self.assertEqual(len(checks), 1)

    def test_html_compression_preserves_content(self):
        import gzip

        plain = self.client.get('/')
        compressed = self.client.get('/', HTTP_ACCEPT_ENCODING='gzip')
        self.assertEqual(compressed.status_code, 200)
        self.assertEqual(compressed['Content-Encoding'], 'gzip')
        self.assertIn('Accept-Encoding', compressed['Vary'])
        self.assertIn(b'<!doctype html>', gzip.decompress(compressed.content).lower())
        self.assertLess(len(compressed.content), len(plain.content) // 2)

    def test_get_exception_does_not_leak_cache_to_later_calls(self):
        def view(request):
            self.assertTrue(local_allows('wms'))
            raise RuntimeError('cleanup')
        with self.assertRaises(RuntimeError):
            RequestReadCacheMiddleware(view)(RequestFactory().get('/'))
        ModuleSwitch.objects.update_or_create(code='wms', defaults={'enabled': False})
        self.assertFalse(local_allows('wms'))

    def test_cached_activation_still_checks_expiry_each_time(self):
        from datetime import timedelta
        from unittest.mock import patch
        from django.utils import timezone
        from bera_control.models import ModuleActivation
        from bera_licensing.services import module_enabled

        now = timezone.now()
        ModuleActivation.objects.create(module='wms', code_digest='test', encrypted_code='test',
                                        activated_at=now, expires_at=now + timedelta(minutes=1))
        def view(request):
            with patch('bera_licensing.services.timezone.now', return_value=now):
                self.assertTrue(module_enabled('wms'))
            with patch('bera_licensing.services.timezone.now', return_value=now + timedelta(minutes=2)):
                self.assertFalse(module_enabled('wms'))
            return HttpResponse('ok')
        RequestReadCacheMiddleware(view)(RequestFactory().get('/'))


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'brand-geometry-performance-test'}})
class RemoteLogoPerformanceTests(TestCase):
    def test_warm_logo_does_not_head_or_download_again(self):
        output = BytesIO()
        Image.new('RGB', (200, 100), 'black').save(output, format='PNG')
        storage = Mock(bucket_name='public-images', endpoint_url='https://test.r2.cloudflarestorage.com')
        storage.open.side_effect = lambda *args: BytesIO(output.getvalue())
        brand = SimpleNamespace(name='Brand', logo=SimpleNamespace(
            storage=storage, name='brands/unique-image.png', url='https://media.example.com/brands/unique-image.png'))
        first = brand_logo(brand)
        second = brand_logo(brand)
        self.assertEqual(first, second)
        storage.get_modified_time.assert_not_called()
        storage.open.assert_called_once()

    def test_missing_remote_logo_is_not_downloaded_for_every_product(self):
        storage = Mock(bucket_name='public-images', endpoint_url='https://test.r2.cloudflarestorage.com')
        storage.open.side_effect = OSError('missing')
        brand = SimpleNamespace(name='Missing', logo=SimpleNamespace(
            storage=storage, name='brands/missing-logo.png', url='https://media.example.com/brands/missing-logo.png'))
        self.assertEqual(brand_logo(brand), brand_logo(brand))
        storage.open.assert_called_once()
