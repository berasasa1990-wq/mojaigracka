import time
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone
from shop.meta_pixel import CAPI_EVENTS, capi_enabled, send_capi
from shop.models import MetaTrackingEvent


class Command(BaseCommand):
    help = 'Deliver Meta CAPI outbox events once or continuously from a background worker.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true', help='Run continuously as a Render Background Worker.')
        parser.add_argument('--retry-failed', action='store_true', help='Requeue recent failed events with their original IDs.')
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--poll', type=float, default=None)

    def handle(self, *args, **options):
        if not capi_enabled():
            raise CommandError('CAPI je isključen: provjerite PIXEL_ID, ENABLED, ACCESS_TOKEN i API_VERSION. Vrijednosti tajni se ne ispisuju.')
        limit = max(1, min(options['limit'], 500))
        poll = options['poll'] if options['poll'] is not None else settings.META_CAPI_POLL_SECONDS
        poll = max(1, min(poll, 60))
        if options['retry_failed']:
            from datetime import timedelta
            MetaTrackingEvent.objects.filter(capi_status='failed', capi_sent_at__isnull=True,
                created_at__gte=timezone.now() - timedelta(hours=24)).update(
                    capi_status='pending', capi_attempts=0, capi_next_attempt_at=timezone.now(),
                    capi_locked_until=None, capi_lock_token=None, capi_last_error='')
        try:
            while True:
                close_old_connections()
                now = timezone.now()
                MetaTrackingEvent.objects.filter(capi_status='processing', capi_sent_at__isnull=True,
                    capi_locked_until__lte=now, capi_attempts__gte=settings.META_CAPI_MAX_ATTEMPTS).update(
                        capi_status='failed', capi_last_error='attempts_exhausted', capi_locked_until=None, capi_lock_token=None)
                events = MetaTrackingEvent.objects.filter(
                    name__in=CAPI_EVENTS, capi_sent_at__isnull=True,
                    capi_status__in=('pending', 'processing'), capi_next_attempt_at__lte=now,
                    capi_attempts__lt=settings.META_CAPI_MAX_ATTEMPTS,
                ).filter(Q(capi_locked_until__isnull=True) | Q(capi_locked_until__lte=now)).order_by('pk')[:limit]
                count = 0
                for event in events:
                    try:
                        count += int(send_capi(event))
                    except Exception:
                        # Never print HTTP bodies, headers, tracebacks or access tokens.
                        self.stderr.write(f'Meta event {event.event_id}: worker_error; lease omogućuje ponovni pokušaj.')
                if count or not options['watch']:
                    self.stdout.write(f'Poslano: {count}')
                if not options['watch']:
                    return
                time.sleep(poll)
        except KeyboardInterrupt:
            self.stdout.write('Meta worker zaustavljen.')
