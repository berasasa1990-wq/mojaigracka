from django.conf import settings
from .registry import MODULES, IMPLEMENTED
from .services import license_details, module_enabled


def licensing_context(request):
    if not request.path.startswith('/panel') or not request.user.is_authenticated or not request.user.is_staff:
        return {}
    details = license_details()
    return {'bera_license_state': details[0] if details else None,
            'bera_modules': [dict(code=code, name=value[0], description=value[1],
                enabled=module_enabled(code), implemented=code in IMPLEMENTED,
                enforced=code in settings.BERA_LICENSE_ENFORCED_MODULES,
                expires_at=details[1] if details and code in settings.BERA_LICENSE_ENFORCED_MODULES else None)
                for code, value in MODULES.items()]}
