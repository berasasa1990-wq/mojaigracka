from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from shop.views import panel_required
from .models import ActivationRequest
from .registry import MODULES


@panel_required
@require_POST
def request_activation(request):
    code = request.POST.get('module')
    if code in MODULES:
        # Administrative queue only; no entitlement fields are changed.
        if not ActivationRequest.objects.filter(module=code, requested_by=request.user).exists():
            ActivationRequest.objects.create(module=code, requested_by=request.user)
        messages.success(request, 'Zahtjev je evidentiran. Za obradu kontaktirajte BERA IT na https://bera-it.com.')
    return redirect('panel_section', section='moduli')
