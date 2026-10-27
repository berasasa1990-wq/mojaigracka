"""Explicit upload/read/public GET probe; never print credentials or delete objects."""
from io import BytesIO
from uuid import uuid4
from urllib.request import urlopen

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from PIL import Image


class Command(BaseCommand):
    help = 'Verify R2 configuration; --upload writes one unique public test PNG (not deleted).'

    def add_arguments(self, parser):
        parser.add_argument('--upload', action='store_true')

    def handle(self, *args, **options):
        if 'r2_images' not in storages.backends:
            raise CommandError('R2 is not configured. Supply its environment variables.')
        storage = storages['r2_images']
        if not options['upload']:
            self.stdout.write('R2 configuration available. Use --upload to verify network upload/read/public GET.')
            return
        output = BytesIO()
        Image.new('RGB', (1, 1), 'white').save(output, format='PNG')
        data = output.getvalue()
        name = 'products/_checks/' + uuid4().hex + '.png'
        try:
            saved = storage.save(name, ContentFile(data))
            with storage.open(saved, 'rb') as uploaded:
                if uploaded.read() != data:
                    raise ValueError
            url = storage.url(saved)
            if not url.startswith('https://' + storage.custom_domain + '/') or '?' in url:
                raise ValueError
            with urlopen(url, timeout=20) as response:
                if response.status != 200 or response.read() != data:
                    raise ValueError
        except Exception:
            # Provider errors can contain signed requests; never echo them.
            raise CommandError('R2 verification failed. Check bucket permissions, endpoint and public domain. '
                               'A test object may remain at ' + name) from None
        self.stdout.write(self.style.SUCCESS('Upload, authenticated read and anonymous public GET: OK'))
        self.stdout.write(url)
        self.stdout.write('Test object retained; remove it manually in R2 if no longer needed.')
