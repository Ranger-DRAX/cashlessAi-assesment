import threading

from django.test import TransactionTestCase

from tenants.models import Tenant
from wallets.exceptions import (
    IdempotencyKeyConflict,
    InsufficientFunds,
    InvalidAmount,
)
from wallets.models import Customer, Transaction, Wallet
from wallets.services import deposit, withdraw


class DepositTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant: Tenant = Tenant.objects.create(name="Deposit Tenant")
        self.customer: Customer = Customer.objects.create(
            tenant=self.tenant, username="alice", email="a@a.com"
        )
        self.wallet: Wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.customer, cached_balance=0
        )

    def test_deposit_increases_balance(self) -> None:
        deposit(self.tenant, self.wallet.id, 5000, "dep-1", "hash-a")
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 5000)

    def test_deposit_creates_transaction(self) -> None:
        txn = deposit(self.tenant, self.wallet.id, 3000, "dep-2", "hash-b")
        self.assertEqual(txn.amount, 3000)
        self.assertEqual(txn.type, "deposit")
        self.assertEqual(txn.status, "completed")

    def test_deposit_invalid_amount_raises(self) -> None:
        with self.assertRaises(InvalidAmount):
            deposit(self.tenant, self.wallet.id, 0, "dep-3", "hash-c")
        with self.assertRaises(InvalidAmount):
            deposit(self.tenant, self.wallet.id, -100, "dep-4", "hash-d")

    def test_idempotent_replay_returns_same_transaction(self) -> None:
        txn1 = deposit(self.tenant, self.wallet.id, 2000, "dep-idem", "hash-same")
        txn2 = deposit(self.tenant, self.wallet.id, 2000, "dep-idem", "hash-same")
        self.assertEqual(txn1.id, txn2.id)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 2000)

    def test_idempotency_conflict_raises(self) -> None:
        deposit(self.tenant, self.wallet.id, 1000, "dep-conflict", "hash-1")
        with self.assertRaises(IdempotencyKeyConflict):
            deposit(self.tenant, self.wallet.id, 2000, "dep-conflict", "hash-2")


class WithdrawTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant: Tenant = Tenant.objects.create(name="Withdraw Tenant")
        self.customer: Customer = Customer.objects.create(
            tenant=self.tenant, username="bob", email="b@b.com"
        )
        self.wallet: Wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.customer, cached_balance=10000
        )

    def test_withdraw_decreases_balance(self) -> None:
        withdraw(self.tenant, self.wallet.id, 3000, "wd-1", "hash-a")
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 7000)

    def test_insufficient_funds_raises_and_changes_nothing(self) -> None:
        original_balance: int = self.wallet.cached_balance
        original_count: int = Transaction.objects.filter(wallet=self.wallet).count()

        with self.assertRaises(InsufficientFunds):
            withdraw(self.tenant, self.wallet.id, 99999, "wd-fail", "hash-f")

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, original_balance)
        self.assertEqual(Transaction.objects.filter(wallet=self.wallet).count(), original_count)

    def test_withdraw_invalid_amount_raises(self) -> None:
        with self.assertRaises(InvalidAmount):
            withdraw(self.tenant, self.wallet.id, 0, "wd-inv", "hash-x")

    def test_idempotent_replay(self) -> None:
        txn1 = withdraw(self.tenant, self.wallet.id, 1000, "wd-idem", "hash-same")
        txn2 = withdraw(self.tenant, self.wallet.id, 1000, "wd-idem", "hash-same")
        self.assertEqual(txn1.id, txn2.id)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 9000)

    def test_idempotency_conflict(self) -> None:
        withdraw(self.tenant, self.wallet.id, 1000, "wd-conflict", "hash-1")
        with self.assertRaises(IdempotencyKeyConflict):
            withdraw(self.tenant, self.wallet.id, 2000, "wd-conflict", "hash-2")


class ConcurrentWithdrawTests(TransactionTestCase):
    def test_concurrent_withdrawals_one_fails(self) -> None:
        tenant: Tenant = Tenant.objects.create(name="Race Tenant")
        customer: Customer = Customer.objects.create(
            tenant=tenant, username="racer", email="r@r.com"
        )
        wallet: Wallet = Wallet.objects.create(
            tenant=tenant, customer=customer, cached_balance=10000
        )

        results: list[str] = []
        barrier = threading.Barrier(2, timeout=5)

        def do_withdraw(key: str, hash_val: str) -> None:
            try:
                barrier.wait()
                withdraw(tenant, wallet.id, 7000, key, hash_val)
                results.append("success")
            except InsufficientFunds:
                results.append("insufficient")
            except Exception as exc:
                results.append(f"error:{exc}")

        t1 = threading.Thread(target=do_withdraw, args=("race-wd-1", "h1"))
        t2 = threading.Thread(target=do_withdraw, args=("race-wd-2", "h2"))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertIn("success", results)
        self.assertIn("insufficient", results)
        self.assertEqual(results.count("success"), 1)
        self.assertEqual(results.count("insufficient"), 1)

        wallet.refresh_from_db()
        self.assertEqual(wallet.cached_balance, 3000)
