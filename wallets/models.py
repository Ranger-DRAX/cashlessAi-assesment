"""Domain models for the wallets app: Customer, Wallet, and Transaction.

All monetary values are stored as integer minor units (paisa/cents) — never
as floats — per the non-negotiable rule in AGENT.md.
"""

import uuid

from django.db import models

from tenants.models import Tenant


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------


class Customer(models.Model):
    """A customer belonging to a specific tenant.

    Attributes:
        id: UUID primary key.
        tenant: The tenant this customer belongs to.
        username: Unique per tenant (enforced at the DB level).
        email: Customer's email address.
        created_at: Timestamp of creation.
    """

    id: models.UUIDField = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    tenant: models.ForeignKey = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="customers",
    )
    username: models.CharField = models.CharField(max_length=150)
    email: models.EmailField = models.EmailField()
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "username"],
                name="unique_customer_per_tenant",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Customer({self.username}, tenant={self.tenant_id})"


# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------


class Wallet(models.Model):
    """A wallet holding funds in minor currency units for a specific customer.

    ``cached_balance`` is a convenience field — it is only ever written inside
    the same ``transaction.atomic()`` block as the ledger row that justifies
    the change.  If it and the ledger ever disagree, the ledger wins.

    Attributes:
        id: UUID primary key.
        tenant: The tenant this wallet belongs to.
        customer: The customer who owns this wallet.
        currency: ISO 4217 currency code (default ``"BDT"``).
        cached_balance: Balance in minor units (paisa/cents), default 0.
        created_at: Timestamp of creation.
    """

    id: models.UUIDField = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    tenant: models.ForeignKey = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="wallets",
    )
    customer: models.ForeignKey = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="wallets",
    )
    currency: models.CharField = models.CharField(max_length=3, default="BDT")
    cached_balance: models.BigIntegerField = models.BigIntegerField(default=0)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"Wallet({self.id}, customer={self.customer_id}, "
            f"balance={self.cached_balance} {self.currency})"
        )


# ---------------------------------------------------------------------------
# Transaction (the immutable ledger)
# ---------------------------------------------------------------------------


class TransactionType(models.TextChoices):
    """Allowed transaction types.

    Direction is implied by the type — ``amount`` is always positive.
    """

    DEPOSIT = "deposit", "Deposit"
    WITHDRAW = "withdraw", "Withdraw"
    TRANSFER_DEBIT = "transfer_debit", "Transfer Debit"
    TRANSFER_CREDIT = "transfer_credit", "Transfer Credit"


class TransactionStatus(models.TextChoices):
    """Allowed transaction statuses."""

    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class Transaction(models.Model):
    """An immutable ledger entry recording a single balance change.

    Every balance change produces exactly one ``Transaction`` row.  Transfers
    produce two linked rows (one debit, one credit) joined via
    ``related_transaction``.

    Attributes:
        id: UUID primary key.
        tenant: The tenant this transaction belongs to.
        wallet: The wallet affected by this transaction.
        type: One of ``TransactionType`` choices.
        amount: Always-positive value in minor currency units.
        related_transaction: Self-FK linking the two legs of a transfer.
        idempotency_key: Client-supplied key; unique per tenant at the DB
            level, making concurrent duplicate requests safe.
        status: One of ``TransactionStatus`` choices.
        created_at: Timestamp of creation.
    """

    id: models.UUIDField = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    tenant: models.ForeignKey = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    wallet: models.ForeignKey = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    type: models.CharField = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
    )
    amount: models.BigIntegerField = models.BigIntegerField(
        help_text="Always positive; direction is implied by the transaction type.",
    )
    related_transaction: models.ForeignKey = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="linked_transaction",
    )
    idempotency_key: models.CharField = models.CharField(
        max_length=255,
        db_index=True,
    )
    status: models.CharField = models.CharField(
        max_length=10,
        choices=TransactionStatus.choices,
        default=TransactionStatus.COMPLETED,
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="unique_idempotency_key_per_tenant",
            ),
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="transaction_amount_positive",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"Transaction({self.type}, amount={self.amount}, "
            f"wallet={self.wallet_id}, status={self.status})"
        )
