from django.urls import path
from . import views
app_name = 'bera_control'
urlpatterns = [
    path('monthly-rebate/', views.set_monthly_rebate, name='set_monthly_rebate'),
    path('modules/<slug:code>/price/', views.set_price, name='set_price'),
    path('', views.login, name='login'),
    path('setup/', views.setup, name='setup'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('modules/<slug:code>/', views.toggle, name='toggle'),
    path('modules/<slug:code>/code/', views.generate_code, name='generate_code'),
    path('modules/<slug:code>/duration/', views.set_duration, name='set_duration'),
    path('logout/', views.logout, name='logout'),
]
