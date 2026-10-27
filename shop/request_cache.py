"""Memoize repeated reads only within one read-only HTTP request."""
from contextvars import ContextVar

_reads = ContextVar('shop_request_reads', default=None)


def request_read(key, load):
    values = _reads.get()
    if values is None:
        return load()
    if key not in values:
        values[key] = load()
    return values[key]


class RequestReadCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _reads.set({} if request.method in ('GET', 'HEAD') else None)
        try:
            return self.get_response(request)
        finally:
            _reads.reset(token)
