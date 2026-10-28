"""Copy only database-referenced public images, without rewriting database names."""
import hashlib
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.files import File
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

from shop.storage import PUBLIC_IMAGE_FIELDS, PUBLIC_PREFIXES


def digest(stream):
    checksum = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        checksum.update(block)
    return checksum.digest()


class Command(BaseCommand):
    help = 'Dry-run public-image migration by default; --apply copies to R2 without deleting or overwriting.'

    def add_arguments(self, parser):
        parser.add_argument('--source-root', default=None)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        root = Path(options['source_root'] or settings.MEDIA_ROOT).resolve()
        if not root.is_dir():
            raise CommandError('Source media directory does not exist.')
        names = set()
        for model_name, fields in PUBLIC_IMAGE_FIELDS.items():
            model = apps.get_model('shop', model_name)
            for field in fields:
                names.update(model.objects.exclude(**{field: ''}).values_list(field, flat=True))
        for model_name in ('Product', 'ProductImage'):
            for manifest in apps.get_model('shop', model_name).objects.values_list('image_variants', flat=True):
                for label in ('thumbnail', 'card', 'main'):
                    key = manifest.get(label, {}).get('name') if isinstance(manifest, dict) else None
                    if key:
                        names.add(key)
        names.discard(None)
        target = None
        if options['apply']:
            if 'r2_images' not in storages.backends:
                raise CommandError('Configure R2 before --apply. R2_ENABLED=false permits staging.')
            target = storages['r2_images']
        missing = conflicts = copied = matched = 0
        for name in sorted(names):
            source = (root / name).resolve()
            if (not source.is_relative_to(root) or not name.startswith(PUBLIC_PREFIXES)
                    or '..' in Path(name).parts or '\\' in name):
                raise CommandError('Unsafe or non-public image reference; migration stopped.')
            if not source.is_file():
                missing += 1
                self.stdout.write('MISSING ' + name)
                continue
            if target is None:
                self.stdout.write('WOULD CHECK/COPY ' + name)
                continue
            try:
                with source.open('rb') as local:
                    expected = digest(local)
                if target.exists(name):
                    with target.open(name, 'rb') as remote:
                        equal = digest(remote) == expected
                    if equal:
                        matched += 1
                        continue
                    conflicts += 1
                    self.stdout.write('CONFLICT (not overwritten) ' + name)
                    continue
                with source.open('rb') as local:
                    saved = target.save(name, File(local))
                if saved != name:
                    raise ValueError('Concurrent collision')
                with target.open(saved, 'rb') as remote:
                    if digest(remote) != expected:
                        raise ValueError('Read-back mismatch')
                copied += 1
                self.stdout.write('VERIFIED ' + name)
            except Exception:
                raise CommandError('R2 copy/read verification failed; database and source files unchanged. '
                                   'Inspect object in R2: ' + name) from None
        self.stdout.write(f'References: {len(names)}; copied: {copied}; identical: {matched}; '
                          f'missing: {missing}; conflicts: {conflicts}')
        if missing or conflicts:
            raise CommandError('Migration incomplete. Recover missing sources/resolve conflicts before enabling R2.')
        if target is None:
            self.stdout.write('DRY RUN: no files uploaded; no database changes.')
