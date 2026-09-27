"""URL configuration for the Cashless Wallet API project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns: list = [
    path("admin/", admin.site.urls),
    path("api/tenants/", include("tenants.urls")),
    path("api/", include("wallets.urls")),
]
