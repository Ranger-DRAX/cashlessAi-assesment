from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field: str = "django.db.models.BigAutoField"
    name: str = "tenants"
