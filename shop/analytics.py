"""First-party session analytics. No IP addresses or full referring URLs stored."""
import logging
import time
import uuid
from urllib.parse import urlsplit
from django.db import DatabaseError
from django.db.models import Count, Sum
from django.utils import timezone
from datetime import timedelta
from .models import AnalyticsEvent, Product

logger = logging.getLogger(__name__)
PUBLIC = {'home', 'category', 'brand', 'sales', 'new_arrivals', 'bestsellers', 'product_detail', 'cart', 'checkout'}


def attribution(request):
    source = request.GET.get('utm_source', '').strip().lower()[:80]
    medium = request.GET.get('utm_medium', '').strip().lower()
    paid = medium in {'cpc', 'ppc', 'paid', 'paid_social', 'paidsocial', 'paid-social', 'display', 'cpm', 'ads', 'remarketing'}
    aliases = {'fb': 'Facebook', 'facebook': 'Facebook', 'ig': 'Instagram', 'instagram': 'Instagram', 'google': 'Google', 'youtube': 'YouTube', 'tiktok': 'TikTok', 'bing': 'Bing', 'meta': 'Meta (Facebook/Instagram)'}
    if request.GET.get('gclid') or request.GET.get('gbraid') or request.GET.get('wbraid'):
        return 'Google', True
    if request.GET.get('msclkid'):
        return 'Bing', True
    if source:
        return aliases.get(source, source), paid
    host = urlsplit(request.META.get('HTTP_REFERER', '')).hostname or ''
    host = host.lower()
    for domain, label in [('facebook.com', 'Facebook'), ('instagram.com', 'Instagram'), ('google.com', 'Google'), ('tiktok.com', 'TikTok'), ('youtube.com', 'YouTube')]:
        if host == domain or host.endswith('.' + domain):
            return label, False
    if request.GET.get('fbclid'):
        return 'Meta (Facebook/Instagram)', False
    return ('Drugi sajt' if host and host != request.get_host().split(':')[0] else 'Direktno'), False


class AnalyticsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        before = dict(request.session.get('cart', {})) if request.method == 'POST' else {}
        response = self.get_response(request)
        route = request.resolver_match.url_name if request.resolver_match else ''
        agent = request.META.get('HTTP_USER_AGENT', '').lower()
        if request.user.is_staff or any(marker in agent for marker in ('bot', 'spider', 'crawler', 'headless')):
            return response
        if not (200 <= response.status_code < 400):
            return response
        visit = request.method == 'GET' and route in PUBLIC and response.status_code == 200
        cart = request.method == 'POST' and route in {'cart_update', 'cart_add_bundle'}
        if not visit and not cart:
            return response
        try:
            visitor = request.session.get('analytics_visitor') or uuid.uuid4().hex
            request.session['analytics_visitor'] = visitor
            if visit:
                source, paid = attribution(request)
                last = request.session.get('analytics_last_visit', 0)
                campaign = bool(request.GET.get('utm_source') or request.GET.get('gclid') or request.GET.get('msclkid'))
                if time.time() - last > 1800 or (campaign and (source, paid) != tuple(request.session.get('analytics_source', []))):
                    AnalyticsEvent.objects.create(kind='visit', visitor=visitor, source=source, paid=paid)
                    request.session['analytics_source'] = [source, paid]
                request.session['analytics_last_visit'] = time.time()
            source, paid = request.session.get('analytics_source', ['Direktno', False])
            if visit and route == 'product_detail':
                product = Product.objects.filter(pk=request.resolver_match.kwargs.get('pk')).first()
                if product:
                    AnalyticsEvent.objects.create(kind='view', visitor=visitor, source=source, paid=paid, product=product, product_name=product.name)
            if cart:
                additions = {key: value - before.get(key, 0) for key, value in request.session.get('cart', {}).items() if value > before.get(key, 0)}
                for product in Product.objects.filter(pk__in=additions):
                    AnalyticsEvent.objects.create(kind='cart', visitor=visitor, source=source, paid=paid, product=product, product_name=product.name, quantity=additions[str(product.pk)])
        except DatabaseError:
            logger.warning('Analytics storage unavailable', exc_info=True)
        return response


def dashboard(days):
    events = AnalyticsEvent.objects.all()
    if days:
        events = events.filter(created_at__gte=timezone.now() - timedelta(days=days))
    visits = events.filter(kind='visit')
    return {
        'visitors': visits.values('visitor').distinct().count(),
        'ad_visitors': visits.filter(paid=True).values('visitor').distinct().count(),
        'sources': visits.values('source', 'paid').annotate(people=Count('visitor', distinct=True), visits=Count('pk')).order_by('-people'),
        'views': events.filter(kind='view').values('product_id', 'product_name').annotate(count=Count('pk')).order_by('-count')[:30],
        'cart_additions': events.filter(kind='cart').values('product_id', 'product_name').annotate(count=Sum('quantity'), actions=Count('pk')).order_by('-count')[:30],
    }
