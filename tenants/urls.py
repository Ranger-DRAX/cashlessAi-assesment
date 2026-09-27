"""URL routing for the tenants app."""

from django.urls import path

from tenants.views import TenantCreateView, TenantPingView

app_name: str = "tenants"

urlpatterns: list = [
    path("", TenantCreateView.as_view(), name="tenant-create"),
    # Temporary — remove once step 4+ views exist.
    path("ping/", TenantPingView.as_view(), name="tenant-ping"),
]
