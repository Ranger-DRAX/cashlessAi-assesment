"""Django app configuration for the tenants app."""

from django.apps import AppConfig


class TenantsConfig(AppConfig):
    """Configuration for the tenants application."""

    default_auto_field: str = "django.db.models.BigAutoField"
    name: str = "tenants"
