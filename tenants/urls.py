from django.urls import path

from tenants.views import TenantCreateView, TenantPingView

app_name = "tenants"

urlpatterns = [
    path("", TenantCreateView.as_view(), name="tenant-create"),
    path("ping/", TenantPingView.as_view(), name="tenant-ping"),
]
