"""Local-only encoding benchmark: never writes media, database rows or R2 objects."""
from io import BytesIO
import json
from pathlib import Path
import platform
import statistics
import time

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings
from PIL import Image, ImageDraw, __version__ as pillow_version

from shop.product_images import prepare_product_image


class Command(BaseCommand):
    help = 'Measure product image encoding in memory, with synthetic or explicitly supplied local inputs.'

    def add_arguments(self, parser):
        parser.add_argument('--input', action='append', default=[])
        parser.add_argument('--runs', type=int, default=3)
        parser.add_argument('--try-avif', action='store_true')

    def handle(self, *args, **options):
        if not 1 <= options['runs'] <= 10:
            raise CommandError('--runs must be between 1 and 10.')
        inputs = []
        for filename in options['input']:
            path = Path(filename)
            if not path.is_file():
                raise CommandError('Input image does not exist.')
            inputs.append((path.name, path.read_bytes()))
        if not inputs:
            smooth = Image.linear_gradient('L').resize((1600, 1200)).convert('RGB')
            ImageDraw.Draw(smooth).text((160, 140), 'MOJA IGRACKA - DETALJI', fill='navy', stroke_width=1)
            noise = Image.effect_noise((1600, 1200), 65).convert('RGB')
            alpha = Image.new('RGBA', (1600, 1200), (0, 140, 220, 0))
            draw = ImageDraw.Draw(alpha)
            draw.ellipse((100, 100, 1500, 1100), fill=(25, 160, 220, 120))
            draw.rectangle((400, 300, 1200, 900), fill=(230, 50, 90, 255))
            for name, image in [('gradient-text', smooth), ('high-detail-noise', noise), ('transparent', alpha)]:
                output = BytesIO()
                image.save(output, 'PNG')
                inputs.append((name + '.png', output.getvalue()))
        report = {'pillow': pillow_version, 'architecture': platform.machine(), 'runs': options['runs'],
                  'avif_probe': options['try_avif'], 'scope': 'local encoding only; excludes R2 network', 'samples': []}
        with override_settings(PRODUCT_IMAGE_TRY_AVIF=options['try_avif']):
            for name, data in inputs:
                times, cpu_times, avif_times = [], [], []
                for _ in range(options['runs']):
                    started, cpu = time.perf_counter(), time.process_time()
                    result = prepare_product_image(ContentFile(data, name=name))
                    if result._product_avif_probe_ms is not None:
                        avif_times.append(result._product_avif_probe_ms)
                    times.append((time.perf_counter() - started) * 1000)
                    cpu_times.append((time.process_time() - cpu) * 1000)
                variants = {label: {key: value for key, value in item.items() if key != 'file'}
                            for label, item in result._product_derivatives.items()}
                report['samples'].append({'input': name, 'input_bytes': len(data),
                    'median_ms': round(statistics.median(times), 2), 'max_ms': round(max(times), 2),
                    'median_cpu_ms': round(statistics.median(cpu_times), 2),
                    'median_avif_probe_ms': round(statistics.median(avif_times), 2) if avif_times else None,
                    'variants': variants})
        self.stdout.write(json.dumps(report, indent=2))
