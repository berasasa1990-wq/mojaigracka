"""Storage selection for public artwork; default/private storage stays separate."""
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import storages

PUBLIC_IMAGE_FIELDS = {
    'ProductImage': ('image',), 'Brand': ('logo',), 'Category': ('image',), 'Product': ('image',),
    'StoreSettings': ('logo',), 'Banner': ('image', 'secondary_image'),
    'SEOSettings': ('social_image', 'favicon'),
}
PUBLIC_PREFIXES = ('brands/', 'categories/', 'products/', 'store/', 'banners/', 'seo/')


def r2_configuration(environ):
    """Absent credentials keep local storage; partial config must never silently fall back."""
    required = ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_S3_ENDPOINT_URL')
    names = required + ('AWS_STORAGE_BUCKET_NAME', 'AWS_S3_CUSTOM_DOMAIN', 'AWS_S3_REGION_NAME')
    supplied = any(environ.get(name, '').strip() for name in names)
    flag = environ.get('R2_ENABLED', 'auto').lower().strip()
    if flag not in ('auto', 'true', 'false'):
        raise ImproperlyConfigured('R2_ENABLED must be auto, true or false.')
    if not supplied:
        if flag == 'true':
            raise ImproperlyConfigured('R2_ENABLED requires R2 credentials and endpoint.')
        return None, False
    missing = [name for name in required if not environ.get(name, '').strip()]
    if missing:
        raise ImproperlyConfigured('Incomplete R2 configuration; missing: ' + ', '.join(missing))
    endpoint = environ['AWS_S3_ENDPOINT_URL'].strip()
    parsed = urlsplit(endpoint)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not parsed.hostname.endswith('.r2.cloudflarestorage.com')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or parsed.port not in (None, 443)):
        raise ImproperlyConfigured('AWS_S3_ENDPOINT_URL must be an HTTPS Cloudflare R2 S3 endpoint.')
    domain = environ.get('AWS_S3_CUSTOM_DOMAIN', 'media.mojaigracka.com').strip()
    if not domain or any(c in domain for c in '/:@?# \\'):
        raise ImproperlyConfigured('AWS_S3_CUSTOM_DOMAIN must be a hostname without scheme or path.')
    region = environ.get('AWS_S3_REGION_NAME', 'auto').strip()
    if region != 'auto':
        raise ImproperlyConfigured('Cloudflare R2 requires AWS_S3_REGION_NAME=auto.')
    bucket = environ.get('AWS_STORAGE_BUCKET_NAME', 'mojaigracka-media').strip()
    if not bucket:
        raise ImproperlyConfigured('AWS_STORAGE_BUCKET_NAME cannot be empty.')
    from botocore.config import Config
    return {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'access_key': environ['AWS_ACCESS_KEY_ID'].strip(),
            'secret_key': environ['AWS_SECRET_ACCESS_KEY'].strip(),
            'bucket_name': bucket, 'endpoint_url': endpoint,
            'region_name': region, 'custom_domain': domain,
            'querystring_auth': False, 'default_acl': None,
            'file_overwrite': False, 'location': '',
            'url_protocol': 'https:', 'signature_version': 's3v4',
            'object_parameters': {},
            'client_config': Config(
                signature_version='s3v4',
                request_checksum_calculation='when_required',
                response_checksum_validation='when_required',
                connect_timeout=5, read_timeout=20,
                retries={'max_attempts': 2},
            ),
        },
    }, flag != 'false'


def public_image_storage():
    """Serializable callable attached only to explicitly public image fields."""
    return storages['public_images']


def product_upload_configuration(public_config):
    """Same bucket/keys, with fail-fast network settings for new derivatives only."""
    from botocore.config import Config
    from boto3.s3.transfer import TransferConfig
    options = dict(public_config['OPTIONS'])
    options['client_config'] = options['client_config'].merge(Config(
        connect_timeout=2, read_timeout=5, retries={'total_max_attempts': 1}))
    options['transfer_config'] = TransferConfig(use_threads=False)
    return {'BACKEND': public_config['BACKEND'], 'OPTIONS': options}


def save_product_derivatives(default_storage, files):
    """Three independent new keys; no overwrites, deletes or database access here."""
    from django.conf import settings
    from storages.backends.s3 import S3Storage
    storage = (storages['public_image_uploads']
               if settings.R2_IMAGES_ENABLED and 'public_image_uploads' in storages.backends
               else default_storage)
    if isinstance(storage, S3Storage):
        from concurrent.futures import ThreadPoolExecutor
        # All submitted uploads are joined before leaving the request. These are
        # bounded network calls, not untracked background jobs or a task queue.
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix='product-media') as executor:
            jobs = {label: executor.submit(storage.save, name, content) for label, (name, content) in files.items()}
            return {label: job.result() for label, job in jobs.items()}
    return {label: storage.save(name, content) for label, (name, content) in files.items()}
