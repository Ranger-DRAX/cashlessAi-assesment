from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet

from tenants.models import Tenant
from wallets.exceptions import CustomerNotFound, WalletNotFound
from wallets.models import Customer, Transaction, Wallet


def get_wallet_for_tenant(tenant: Tenant, wallet_id: UUID) -> Wallet:
    try:
        return Wallet.objects.get(id=wallet_id, tenant=tenant)
    except Wallet.DoesNotExist:
        raise WalletNotFound(f"Wallet {wallet_id} not found.")


def get_wallet_for_tenant_locked(tenant: Tenant, wallet_id: UUID) -> Wallet:
    try:
        return Wallet.objects.select_for_update().get(id=wallet_id, tenant=tenant)
    except Wallet.DoesNotExist:
        raise WalletNotFound(f"Wallet {wallet_id} not found.")


def get_balance(wallet: Wallet) -> int:
    return wallet.cached_balance


def get_transaction_history(tenant: Tenant, wallet: Wallet) -> QuerySet[Transaction]:
    return Transaction.objects.filter(tenant=tenant, wallet=wallet).order_by("-created_at")


def get_customer_for_tenant(tenant: Tenant, customer_id: UUID) -> Customer:
    try:
        return Customer.objects.get(id=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        raise CustomerNotFound(f"Customer {customer_id} not found.")
