"""Admin registration for the Tenant model."""

from django.contrib import admin

from tenants.models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    """Admin view for :class:`Tenant`."""

    list_display = ("name", "api_key", "created_at")
    search_fields = ("name", "api_key")
    readonly_fields = ("id", "created_at")
