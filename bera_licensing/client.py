import json
import ssl
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from django.conf import settings
from .security import LicenseError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LicenseError('redirect_refused')


def fetch_license():
    url = settings.BERA_LICENSE_SERVER_URL
    parsed = urlsplit(url)
    credential = settings.BERA_LICENSE_API_CREDENTIAL
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LicenseError('invalid_server_url')
    if not credential or not settings.BERA_LICENSE_INSTALLATION_ID or any(c in credential for c in '\r\n'):
        raise LicenseError('missing_configuration')
    body = json.dumps({'installation_id': settings.BERA_LICENSE_INSTALLATION_ID,
                       'platform_version': settings.BERA_PLATFORM_VERSION, 'protocol_version': 1}).encode()
    request = Request(url.rstrip('/') + '/sync/', data=body, method='POST', headers={
        'Authorization': 'Bearer ' + credential, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(request, timeout=10) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise LicenseError('response_too_large')
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            return json.loads(raw, object_pairs_hook=unique_pairs)
    except LicenseError:
        raise
    except Exception:
        raise LicenseError('sync_unavailable') from None
