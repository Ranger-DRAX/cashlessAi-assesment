"""Tenant-scoped read operations for wallets, customers, and transactions.

Every function in this module requires ``tenant`` as its first argument,
making it literally impossible to return another tenant's data.  No other
module in the codebase is allowed to query ``Wallet``, ``Customer``, or
``Transaction`` directly — all reads go through here (AGENT.md code quality
bar: "All reads go through selectors.py").
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet

from tenants.models import Tenant
from wallets.exceptions import CustomerNotFound, WalletNotFound
from wallets.models import Customer, Transaction, Wallet


def get_wallet_for_tenant(tenant: Tenant, wallet_id: UUID) -> Wallet:
    """Look up a wallet by ID, scoped to the given tenant.

    Args:
        tenant: The tenant the wallet must belong to.
        wallet_id: The UUID of the wallet to retrieve.

    Returns:
        The matching :class:`~wallets.models.Wallet` instance.

    Raises:
        WalletNotFound: If no wallet with this ID exists under this tenant.
            This converts a cross-tenant lookup into a clean 404 instead
            of leaking a 403 or raising ``Wallet.DoesNotExist`` uncaught.
    """
    try:
        return Wallet.objects.get(id=wallet_id, tenant=tenant)
    except Wallet.DoesNotExist:
        raise WalletNotFound(
            f"Wallet {wallet_id} not found for tenant {tenant.id}."
        )


def get_balance(wallet: Wallet) -> int:
    """Return the wallet's cached balance in minor currency units.

    This trusts ``cached_balance`` and is intentionally cheap — it does
    **not** re-sum the ledger.  ``cached_balance`` is only ever written
    inside the same ``transaction.atomic()`` block as the ``Transaction``
    row that justifies the change, so it is always consistent with the
    ledger.

    Args:
        wallet: The wallet whose balance to read.

    Returns:
        The cached balance as an integer (minor units).
    """
    return wallet.cached_balance


def get_transaction_history(
    tenant: Tenant, wallet: Wallet
) -> QuerySet[Transaction]:
    """Return the transaction history for a wallet, scoped to the tenant.

    Results are ordered newest-first and returned as an unevaluated
    ``QuerySet`` — pagination is the view's responsibility, not the
    selector's.

    Args:
        tenant: The tenant the transactions must belong to.
        wallet: The wallet whose transactions to retrieve.

    Returns:
        A ``QuerySet[Transaction]`` ordered by ``-created_at``.
    """
    return Transaction.objects.filter(
        tenant=tenant,
        wallet=wallet,
    ).order_by("-created_at")


def get_customer_for_tenant(tenant: Tenant, customer_id: UUID) -> Customer:
    """Look up a customer by ID, scoped to the given tenant.

    Args:
        tenant: The tenant the customer must belong to.
        customer_id: The UUID of the customer to retrieve.

    Returns:
        The matching :class:`~wallets.models.Customer` instance.

    Raises:
        CustomerNotFound: If no customer with this ID exists under this
            tenant — producing a 404, never a 403 (AGENT.md rule 1).
    """
    try:
        return Customer.objects.get(id=customer_id, tenant=tenant)
    except Customer.DoesNotExist:
        raise CustomerNotFound(
            f"Customer {customer_id} not found for tenant {tenant.id}."
        )
