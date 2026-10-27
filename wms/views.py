from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from shop.models import Product, StoreSettings
from bera_licensing.services import require_module
from .forms import LocationCreateForm, LocationForm
from .models import Location, ProductLocation, StockMovement

staff_required = user_passes_test(
    lambda user: user.is_active and (user.is_staff or user.is_superuser), login_url='panel_login')


def page_context(**kwargs):
    return {'site_settings': StoreSettings.objects.filter(pk=1).first(), **kwargs}


@staff_required
@never_cache
@require_http_methods(['GET', 'POST'])
def orders(request):
    require_module('wms')
    from shop.views import panel
    return panel(request, section='narudzbe', orders_in_wms=True)


@staff_required
@never_cache
@require_GET
def dashboard(request):
    require_module('wms')
    products = Product.objects.select_related('category', 'brand', 'warehouse_location__location').order_by('name', 'pk')
    query = request.GET.get('q', '').strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(warehouse_location__location__name__icontains=query))
    return render(request, 'wms/dashboard.html', page_context(
        section='articles', page_obj=Paginator(products, 10).get_page(request.GET.get('page')),
        query=query, product_count=products.count(),
        stock_total=products.aggregate(total=Sum('stock'))['total'] or 0,
        unavailable_count=products.filter(stock=0).count(),
    ))


@staff_required
@never_cache
@require_http_methods(['GET', 'POST'])
def locations(request):
    require_module('wms')
    form = LocationCreateForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Lokacija je kreirana.')
        return redirect('wms:locations')
    query = request.GET.get('q', '').strip()
    rows = Location.objects.annotate(
        product_count=Count('product_locations'),
        stock_total=Sum('product_locations__quantity', default=0),
    ).order_by('name', 'pk')
    if query:
        rows = rows.filter(name__icontains=query)
    return render(request, 'wms/locations.html', page_context(
        section='locations', query=query, form=form,
        page_obj=Paginator(rows, 50).get_page(request.GET.get('page')),
    ))


@staff_required
@never_cache
@require_http_methods(['GET', 'POST'])
def product_location(request, pk):
    require_module('wms')
    product = get_object_or_404(Product, pk=pk)
    location = ProductLocation.objects.filter(product=product).first()
    form = LocationForm(request.POST if request.method == 'POST' else None, instance=location, product=product)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product.pk)
            ProductLocation.objects.update_or_create(product=product, defaults={
                'location': form.cleaned_data['location'], 'quantity': form.cleaned_data['quantity'],
            })
            product.stock = form.cleaned_data['quantity']
            product.is_out_of_stock = product.stock == 0
            product._stock_reason = form.cleaned_data['reason'] or f'WMS: izmjena stanja / lokacija {form.cleaned_data["location"] or "nije dodijeljena"}'
            product.save(update_fields=['stock', 'is_out_of_stock'])
        messages.success(request, 'Lokacija artikla je sačuvana.')
        return redirect('wms:dashboard')
    return render(request, 'wms/product_form.html', page_context(section='articles', form=form, product=product))


@staff_required
@never_cache
@require_GET
def history(request):
    require_module('wms')
    query = request.GET.get('q', '').strip()
    movements = StockMovement.objects.all()
    if query:
        movements = movements.filter(Q(product_name__icontains=query) | Q(reason__icontains=query))
    return render(request, 'wms/history.html', page_context(
        section='history', query=query,
        page_obj=Paginator(movements, 50).get_page(request.GET.get('page')),
    ))


def print_context(orders):
    from decimal import Decimal
    documents = []
    for order in orders:
        items = list(order.items.all())
        for item in items:
            item.line_total = item.unit_price * item.quantity
        documents.append({'order': order, 'items': items,
                          'subtotal': sum((item.line_total for item in items), Decimal('0'))})
    return documents


@staff_required
@never_cache
@require_GET
def order_print(request, pk):
    from shop.models import Order
    require_module('wms')
    order = get_object_or_404(Order.objects.exclude(status='draft').prefetch_related('items__product'), pk=pk)
    documents = print_context([order])
    return render(request, 'wms/order_print.html', page_context(documents=documents, **documents[0]))


def selected_print_orders(request):
    from shop.models import Order
    from django.core.exceptions import BadRequest
    ids = request.GET.getlist('orders') if request.method == 'GET' else request.POST.getlist('orders')
    if not ids or len(ids) > 100 or any(not value.isdecimal() or len(value) > 18 for value in ids):
        raise BadRequest('Odaberite između 1 i 100 narudžbi.')
    orders = list(Order.objects.exclude(status='draft').filter(pk__in=ids).prefetch_related('items__product').order_by('pk'))
    if len(orders) != len(set(ids)):
        raise BadRequest('Odabrane narudžbe nisu dostupne.')
    return orders


@staff_required
@never_cache
@require_GET
def orders_bulk_print(request):
    require_module('wms')
    return render(request, 'wms/order_print.html', page_context(documents=print_context(selected_print_orders(request))))


@staff_required
@never_cache
@require_http_methods(['POST'])
def orders_mark_printed(request):
    from shop.models import Order
    from django.utils import timezone
    require_module('wms')
    orders = selected_print_orders(request)
    Order.objects.filter(pk__in=[order.pk for order in orders], printed_at__isnull=True).update(printed_at=timezone.now())
    messages.success(request, 'Narudžbe su označene kao odštampane.')
    return redirect('wms:orders')
