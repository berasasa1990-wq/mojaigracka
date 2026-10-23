import logging
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone
from .client import fetch_license
from .models import LicenseState
from .registry import MODULES
from .security import LicenseError, verify_document

logger = logging.getLogger(__name__)


def sync_license(*, force=False):
    installation = settings.BERA_LICENSE_INSTALLATION_ID
    if not installation:
        raise LicenseError('missing_configuration')
    state, _ = LicenseState.objects.get_or_create(installation_id=installation)
    now = timezone.now()
    token = str(uuid.uuid4())
    eligible = LicenseState.objects.filter(pk=state.pk).filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
    if not force:
        eligible = eligible.filter(Q(next_attempt__isnull=True) | Q(next_attempt__lte=now))
    if not eligible.update(lease_token=token, lease_until=now + timedelta(seconds=60), last_attempt=now):
        return False
    owned = LicenseState.objects.filter(pk=state.pk, lease_token=token)
    try:
        document = fetch_license()
        issued, _, _ = verify_document(document, accepting=True)
        state.refresh_from_db()
        if document['license_version'] < state.version:
            raise LicenseError('stale_license')
        if document['license_version'] == state.version and document != state.document:
            raise LicenseError('version_conflict')
        if state.document:
            try:
                previous_issued = verify_document(state.document)[0]
            except LicenseError:
                previous_issued = None  # Allow recovery from corrupt cache or a rotated public key.
            if previous_issued is not None and issued < previous_issued:
                raise LicenseError('stale_license')
        # Conditional version + lease update works across workers without process-local locks.
        changed = owned.filter(version=state.version).update(
            document=document, version=document['license_version'], last_success=timezone.now(),
            last_error='', next_attempt=now + timedelta(seconds=settings.BERA_LICENSE_REFRESH_INTERVAL),
            lease_token='', lease_until=None)
        return bool(changed)
    except LicenseError as exc:
        owned.update(last_error=str(exc), next_attempt=now + timedelta(seconds=settings.BERA_LICENSE_REFRESH_INTERVAL), lease_token='', lease_until=None)
        logger.warning('BERA license sync failed: %s', exc)
        raise


def license_details():
    try:
        state = LicenseState.objects.filter(installation_id=settings.BERA_LICENSE_INSTALLATION_ID).first()
        if state is None or not state.document:
            return None
        issued, expires, grace = verify_document(state.document)
        if state.version != state.document['license_version']:
            return None
        limit = min(grace, expires + timedelta(seconds=settings.BERA_LICENSE_GRACE_PERIOD))
        return state, expires, limit
    except (LicenseError, DatabaseError):
        return None


def module_enabled(code):
    if code not in MODULES:
        return False
    if code not in settings.BERA_LICENSE_ENFORCED_MODULES:
        # Only the existing Loyalty behavior is preserved during staged rollout.
        if code == 'loyalty':
            from shop.modules import legacy_loyalty_enabled
            return legacy_loyalty_enabled()
        return False
    details = license_details()
    return bool(details and timezone.now() < details[2] and details[0].document['modules'].get(code) is True)


def require_module(code):
    """Use in business operations and jobs; no HTTP dependency."""
    if not module_enabled(code):
        raise PermissionDenied('Modul nije aktivan.')
