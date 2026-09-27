"""Admin registration for Customer, Wallet, and Transaction models."""

from django.contrib import admin

from wallets.models import Customer, Transaction, Wallet


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """Admin view for :class:`Customer`."""

    list_display = ("username", "email", "tenant", "created_at")
    list_filter = ("tenant",)
    search_fields = ("username", "email")
    readonly_fields = ("id", "created_at")


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    """Admin view for :class:`Wallet`."""

    list_display = ("id", "customer", "tenant", "currency", "cached_balance", "created_at")
    list_filter = ("tenant", "currency")
    search_fields = ("customer__username",)
    readonly_fields = ("id", "created_at")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Admin view for :class:`Transaction`."""

    list_display = (
        "id",
        "type",
        "amount",
        "wallet",
        "tenant",
        "status",
        "idempotency_key",
        "created_at",
    )
    list_filter = ("type", "status", "tenant")
    search_fields = ("idempotency_key",)
    readonly_fields = ("id", "created_at")
