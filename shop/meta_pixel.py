"""Meta browser events and an opt-in CAPI outbox. Tokens never enter HTML."""
import hashlib
import json
import logging
import ipaddress
import re
import unicodedata
from datetime import timedelta
from urllib.error import HTTPError, URLError
import uuid
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from django.conf import settings
from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.html import json_script
from django.utils.module_loading import import_string
from .models import MetaTrackingEvent, Product

logger = logging.getLogger(__name__)


def enabled():
    return bool(settings.META_PIXEL_ID and settings.META_PIXEL_ID.isdigit())


def consent_allowed(request):
    try:
        if settings.META_CONSENT_CHECK:
            return bool(import_string(settings.META_CONSENT_CHECK)(request))
        if settings.META_CONSENT_COOKIE:
            return request.COOKIES.get(settings.META_CONSENT_COOKIE) == settings.META_CONSENT_GRANTED_VALUE
        return True  # No existing consent manager; configurable hook above.
    except Exception:
        logger.warning('Meta consent check unavailable; tracking denied')
        return False


CAPI_EVENTS = ('ViewContent', 'AddToCart', 'InitiateCheckout', 'Purchase')


def explicit_marketing_consent(request):
    return bool(settings.META_CONSENT_CHECK or settings.META_CONSENT_COOKIE) and consent_allowed(request)


def normalize_phone(value):
    value = str(value or '').strip()
    digits = re.sub(r'[^0-9]', '', value)
    if value.startswith('+'):
        return digits if 8 <= len(digits) <= 15 else ''
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = settings.META_DEFAULT_COUNTRY_CALLING_CODE + digits.lstrip('0')
    elif not digits.startswith(settings.META_DEFAULT_COUNTRY_CALLING_CODE):
        return ''  # Ambiguous national/international number; do not guess.
    return digits if 8 <= len(digits) <= 15 else ''


def client_ip(request):
    address = request.META.get('REMOTE_ADDR', '')
    hops = max(0, settings.META_TRUSTED_PROXY_HOPS)
    if hops:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')
        if len(forwarded) >= hops:
            address = forwarded[-hops].strip()
    try:
        ip = ipaddress.ip_address(address)
        return str(ip) if ip.is_global else ''
    except ValueError:
        return ''


def collect_user_data(request, order=None):
    anonymous = request.session.get('meta_visitor') or uuid.uuid4().hex
    request.session['meta_visitor'] = anonymous
    data = {'external_id': [hashlib.sha256(anonymous.encode()).hexdigest()]}
    agent = request.META.get('HTTP_USER_AGENT', '')[:1024]
    address = client_ip(request)
    if agent:
        data['client_user_agent'] = agent
    if address:
        data['client_ip_address'] = address
    for key in ('fbp', 'fbc'):
        value = request.COOKIES.get('_' + key, '')
        if re.fullmatch(r'fb\.\d+\.\d+\.[A-Za-z0-9_.-]{1,500}', value):
            data[key] = value
    click_id = request.GET.get('fbclid', '')
    if re.fullmatch(r'[A-Za-z0-9_-]{1,500}', click_id):
        request.session['meta_fbc'] = f'fb.1.{int(timezone.now().timestamp() * 1000)}.{click_id}'
    if 'fbc' not in data and request.session.get('meta_fbc'):
        data['fbc'] = request.session['meta_fbc']
    if settings.META_SEND_HASHED_PII and explicit_marketing_consent(request):
        user = getattr(request, 'user', None)
        email = getattr(order, 'email', '') or (getattr(user, 'email', '') if getattr(user, 'is_authenticated', False) else '')
        email = unicodedata.normalize('NFKC', email).strip().lower()
        phone = normalize_phone(getattr(order, 'phone', ''))
        if email and '@' in email:
            data['em'] = [hashlib.sha256(email.encode()).hexdigest()]
        if phone:
            data['ph'] = [hashlib.sha256(phone.encode()).hexdigest()]
    return data


def create_event(request, name, data=None, order=None):
    if not enabled() or not consent_allowed(request) or getattr(getattr(request, 'user', None), 'is_staff', False) or getattr(getattr(request, 'user', None), 'is_superuser', False):
        return None
    user_data = collect_user_data(request, order)
    # Never include query strings, contact fields, passwords, or payment information.
    source_url = request.build_absolute_uri(request.path)[:1000]
    if request.method == 'POST':
        try:
            referring = urlsplit(request.META.get('HTTP_REFERER', ''))
            if referring.scheme in ('https', 'http') and referring.netloc == request.get_host():
                source_url = urlunsplit((referring.scheme, referring.netloc, referring.path, '', ''))[:1000]
        except ValueError:
            pass  # A malformed referrer must never break checkout.
    values = dict(name=name, data=data or {}, user_data=user_data, source_url=source_url,
                  capi_status='pending' if name in CAPI_EVENTS else 'skipped')
    if order is not None:
        return MetaTrackingEvent.objects.get_or_create(order=order, defaults=values)[0]
    return MetaTrackingEvent.objects.create(**values)


def commerce_data(contents, value):
    grouped = {}
    for item in contents:
        key = (item['id'], item['item_price'])
        if key not in grouped:
            grouped[key] = dict(item)
        else:
            grouped[key]['quantity'] += item['quantity']
    contents = list(grouped.values())
    return {'value': float(value), 'currency': 'BAM', 'content_type': 'product',
            'content_ids': list(dict.fromkeys(item['id'] for item in contents)),
            'contents': contents, 'num_items': sum(item['quantity'] for item in contents),
            'quantity': sum(item['quantity'] for item in contents)}


def cart_data(context):
    contents = []
    for item in context['cart_items']:
        for price, quantity in item['price_groups']:
            contents.append({'id': str(item['product'].pk), 'quantity': quantity, 'item_price': float(price)})
    return commerce_data(contents, context['grand_total'])


def purchase_event(request, order, *, payment_method='cod', payment_confirmed=False):
    """Call inside the successful order transaction; cards require verified payment."""
    if order.status not in ('placed', 'shipped', 'completed') or payment_method not in ('cod', 'card') or (payment_method == 'card' and not payment_confirmed):
        return None
    contents = [{'id': str(item.product_id), 'quantity': item.quantity, 'item_price': float(item.unit_price)}
                for item in order.items.all()]
    data = commerce_data(contents, order.total)
    data['order_id'] = str(order.pk)
    return create_event(request, 'Purchase', data, order=order)


def browser_event(event):
    return {'name': event.name, 'event_id': str(event.event_id), 'data': event.data}


def capi_payload(event):
    return {'event_name': event.name, 'event_id': str(event.event_id),
            'event_time': int(event.created_at.timestamp()), 'action_source': 'website',
            'event_source_url': event.source_url, 'custom_data': event.data, 'user_data': event.user_data}


def capi_enabled():
    return bool(enabled() and settings.META_CAPI_ENABLED and settings.META_CAPI_ACCESS_TOKEN
                and re.fullmatch(r'v[0-9]+\.[0-9]+', settings.META_CAPI_API_VERSION))


class CapiDeliveryError(Exception):
    def __init__(self, code, retryable=True):
        self.code, self.retryable = code, retryable
        super().__init__(code)  # Sanitized code only; never a token or Meta response body.


def transmit_capi(event):
    body = {'data': [capi_payload(event)], 'access_token': settings.META_CAPI_ACCESS_TOKEN}
    if settings.META_CAPI_TEST_EVENT_CODE:
        body['test_event_code'] = settings.META_CAPI_TEST_EVENT_CODE
    request = Request(f'https://graph.facebook.com/{settings.META_CAPI_API_VERSION}/{settings.META_PIXEL_ID}/events',
                      data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    timeout = max(1, min(settings.META_CAPI_TIMEOUT, 30))
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as error:
        # HTTP 400 may include transient Meta errors, including throttling.
        transient = error.code in (408, 429) or error.code >= 500
        try:
            details = json.loads(error.read(8192)).get('error', {})
            transient = transient or details.get('is_transient', False) or details.get('code') in (1, 2, 4, 17, 32, 613)
        except (ValueError, TypeError, AttributeError):
            pass
        raise CapiDeliveryError(f'http_{error.code}', transient) from None
    except (URLError, TimeoutError, OSError):
        raise CapiDeliveryError('network_timeout') from None
    except (ValueError, TypeError):
        raise CapiDeliveryError('invalid_response') from None
    if not isinstance(result, dict) or result.get('events_received') != 1:
        raise CapiDeliveryError('event_not_accepted')


def send_capi(event):
    """Worker-only, atomically leased, retryable delivery with a stable event ID."""
    if not capi_enabled() or event.name not in CAPI_EVENTS:
        return False
    now = timezone.now()
    token = uuid.uuid4()
    lease = now + timedelta(seconds=120)
    from django.db.models import Q, F
    claimed = MetaTrackingEvent.objects.filter(
        pk=event.pk, capi_sent_at__isnull=True, capi_status__in=('pending', 'processing'),
        capi_next_attempt_at__lte=now, capi_attempts__lt=settings.META_CAPI_MAX_ATTEMPTS,
    ).filter(Q(capi_locked_until__isnull=True) | Q(capi_locked_until__lte=now)).update(
        capi_status='processing', capi_locked_until=lease, capi_lock_token=token,
        capi_attempts=F('capi_attempts') + 1,
    )
    if not claimed:
        return False
    event.refresh_from_db()
    owned = MetaTrackingEvent.objects.filter(pk=event.pk, capi_lock_token=token)
    if event.created_at < now - timedelta(hours=24):
        owned.update(capi_status='skipped', capi_last_error='expired', capi_locked_until=None, capi_lock_token=None)
        return False
    if event.name == 'Purchase' and (not event.order_id or not event.order or event.order.status not in ('placed', 'shipped', 'completed')):
        owned.update(capi_status='skipped', capi_last_error='order_not_eligible', capi_locked_until=None, capi_lock_token=None)
        return False
    try:
        transmit_capi(event)
    except CapiDeliveryError as error:
        retry = error.retryable and event.capi_attempts < settings.META_CAPI_MAX_ATTEMPTS
        delay = min(3600, max(1, settings.META_CAPI_RETRY_SECONDS) * 2 ** min(event.capi_attempts - 1, 10))
        owned.update(capi_status='pending' if retry else 'failed', capi_last_error=error.code,
                     capi_next_attempt_at=timezone.now() + timedelta(seconds=delay), capi_locked_until=None, capi_lock_token=None)
        logger.warning('Meta CAPI event %s: %s', event.event_id, error.code)
        return False
    owned.update(capi_status='sent', capi_sent_at=timezone.now(), capi_last_error='', capi_locked_until=None, capi_lock_token=None)
    return True


class MetaPixelMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        before = dict(request.session.get('cart', {})) if request.method == 'POST' else {}
        response = self.get_response(request)
        route = request.resolver_match.url_name if request.resolver_match else ''
        if not enabled() or request.user.is_staff or request.user.is_superuser:
            return response
        if not consent_allowed(request):
            # Existing consent manager can revoke queued server delivery as well.
            visitor = request.session.get('meta_visitor')
            if visitor:
                try:
                    with transaction.atomic():
                        digest = hashlib.sha256(visitor.encode()).hexdigest()
                        MetaTrackingEvent.objects.filter(user_data__external_id=[digest], capi_status__in=('pending', 'processing')).update(
                            capi_status='skipped', capi_last_error='consent_revoked')
                    request.session.pop('meta_pending', None)
                    request.session.pop('meta_fbc', None)
                except DatabaseError:
                    logger.warning('Meta consent update unavailable')
            return response
        if request.path.startswith(('/panel', '/admin', '/bera-control', '/wms')) or not 200 <= response.status_code < 400:
            return response
        try:
            # Keep optional tracking errors outside the transaction that created the order.
            with transaction.atomic():
                events = []
                if request.method == 'POST' and route in ('cart_update', 'cart_add_bundle'):
                    from .cart import cart_context
                    context = cart_context(request)
                    contents = []
                    for item in context['cart_items']:
                        old = before.get(str(item['product'].pk), 0)
                        added = item['quantity'] - old
                        if added <= 0:
                            continue
                        units = [price for price, count in item['price_groups'] for _ in range(count)]
                        for price in units[old:]:
                            contents.append({'id': str(item['product'].pk), 'quantity': 1, 'item_price': float(price)})
                    if contents:
                        value = sum(Decimal(str(item['item_price'])) * item['quantity'] for item in contents)
                        event = create_event(request, 'AddToCart', commerce_data(contents, value))
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and isinstance(response, JsonResponse):
                            data = json.loads(response.content)
                            data['meta_event'] = browser_event(event)
                            response.content = json.dumps(data).encode()
                        else:
                            pending = request.session.get('meta_pending', [])
                            request.session['meta_pending'] = (pending + [event.pk])[-20:]
                html = response.get('Content-Type', '').startswith('text/html') and response.status_code == 200
                if not html or request.method != 'GET':
                    return response
                pending = request.session.pop('meta_pending', [])
                events.extend(MetaTrackingEvent.objects.filter(pk__in=pending, name='AddToCart'))
                events.append(create_event(request, 'PageView'))
                if route == 'product_detail':
                    product = Product.objects.get(pk=request.resolver_match.kwargs['pk'])
                    events.append(create_event(request, 'ViewContent', commerce_data(
                        [{'id': str(product.pk), 'quantity': 1, 'item_price': float(product.price)}], product.price)))
                if route == 'checkout':
                    if request.GET.get('success') == '1':
                        order_id = request.session.get('last_order')
                        purchase = MetaTrackingEvent.objects.filter(order_id=order_id, name='Purchase', order__status__in=('placed', 'shipped', 'completed')).first() if order_id else None
                        if purchase and MetaTrackingEvent.objects.filter(pk=purchase.pk, browser_claimed_at__isnull=True).update(browser_claimed_at=timezone.now()):
                            events.append(purchase)
                    else:
                        from .cart import cart_context, checkout_points_context, selected_cart_points
                        context = cart_context(request)
                        context.update(checkout_points_context(request, context, selected_cart_points(request)))
                        events.append(create_event(request, 'InitiateCheckout', cart_data(context)))
                config = {'pixel_id': settings.META_PIXEL_ID, 'events': [browser_event(event) for event in events if event]}
                from django.templatetags.static import static
                markup = str(json_script(config, 'meta-pixel-config')) + f'<script src="{static("meta-pixel.js")}?v=1" defer></script>'
                content = response.content.decode(response.charset)
                if 'id="meta-pixel-config"' not in content:
                    response.content = content.replace('</body>', markup + '</body>').encode(response.charset)
                    response['Cache-Control'] = 'private, no-store'
        except (DatabaseError, ValueError, Product.DoesNotExist):
            logger.warning('Meta tracking unavailable; storefront response retained')
        return response
