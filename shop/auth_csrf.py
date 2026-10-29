"""Identify CSRF failures for one bounded client retry; never bypass validation."""
from django.http import JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure
from django.views.decorators.cache import never_cache


@never_cache
def csrf_failure(request, reason=''):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.path in (
        '/nalog/prijava/', '/nalog/registracija/', '/panel/prijava/', '/nalog/',
    ):
        response = JsonResponse({'code': 'csrf_failed', 'error': 'Sigurnosni token je istekao. Pokušajte ponovo.'}, status=403)
        response['X-Auth-CSRF-Failure'] = '1'
        return response
    return django_csrf_failure(request, reason=reason)
