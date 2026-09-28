import uuid

from django.db import models

from tenants.models import Tenant


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="customers")
    username = models.CharField(max_length=150)
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

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


class Wallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="wallets")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="wallets")
    currency = models.CharField(max_length=3, default="BDT")
    cached_balance = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Wallet({self.id}, balance={self.cached_balance} {self.currency})"


class TransactionType(models.TextChoices):
    DEPOSIT = "deposit", "Deposit"
    WITHDRAW = "withdraw", "Withdraw"
    TRANSFER_DEBIT = "transfer_debit", "Transfer Debit"
    TRANSFER_CREDIT = "transfer_credit", "Transfer Credit"


class TransactionStatus(models.TextChoices):
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class Transaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="transactions")
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.BigIntegerField(
        help_text="Always positive; direction is implied by the transaction type."
    )
    related_transaction = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="linked_transaction"
    )
    idempotency_key = models.CharField(max_length=255, db_index=True)
    request_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Hash of the request payload; used to detect idempotency conflicts.",
    )
    status = models.CharField(
        max_length=10, choices=TransactionStatus.choices, default=TransactionStatus.COMPLETED
    )
    created_at = models.DateTimeField(auto_now_add=True)

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
        return f"Transaction({self.type}, {self.amount}, wallet={self.wallet_id})"
