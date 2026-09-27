"""Django app configuration for the wallets app."""

from django.apps import AppConfig


class WalletsConfig(AppConfig):
    """Configuration for the wallets application."""

    default_auto_field: str = "django.db.models.BigAutoField"
    name: str = "wallets"
