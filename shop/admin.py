from django.contrib import admin
from django.conf import settings
from .models import SiteModule


@admin.register(SiteModule)
class SiteModuleAdmin(admin.ModelAdmin):
    list_display = ['code', 'enabled', 'paid_until', 'updated_at']
    readonly_fields = ['code', 'revision', 'updated_at']
    fields = ['code', 'enabled', 'paid_until', 'revision', 'updated_at']

    def get_readonly_fields(self, request, obj=None):
        if 'loyalty' in settings.BERA_LICENSE_ENFORCED_MODULES:
            return self.fields
        return self.readonly_fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
