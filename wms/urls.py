from django.urls import path

from . import views

app_name = 'wms'

urlpatterns = [
    path('narudzbe/stampa/', views.orders_bulk_print, name='orders_bulk_print'),
    path('narudzbe/odstampano/', views.orders_mark_printed, name='orders_mark_printed'),
    path('narudzbe/<int:pk>/stampa/', views.order_print, name='order_print'),
    path('narudzbe/', views.orders, name='orders'),
    path('istorija/', views.history, name='history'),
    path('', views.dashboard, name='dashboard'),
    path('lokacije/', views.locations, name='locations'),
    path('artikli/<int:pk>/lokacija/', views.product_location, name='product_location'),
]
