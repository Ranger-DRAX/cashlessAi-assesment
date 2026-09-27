import threading

from django.test import TransactionTestCase

from tenants.models import Tenant
from wallets.exceptions import (
    InsufficientFunds,
    InvalidAmount,
    SameWalletTransfer,
    WalletNotFound,
)
from wallets.models import Customer, Transaction, Wallet
from wallets.services import transfer


class TransferTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant: Tenant = Tenant.objects.create(name="Transfer Tenant")
        self.other_tenant: Tenant = Tenant.objects.create(name="Other Tenant")

        self.customer_a: Customer = Customer.objects.create(
            tenant=self.tenant, username="alice", email="a@a.com"
        )
        self.customer_b: Customer = Customer.objects.create(
            tenant=self.tenant, username="bob", email="b@b.com"
        )
        self.other_customer: Customer = Customer.objects.create(
            tenant=self.other_tenant, username="eve", email="e@e.com"
        )

        self.wallet_a: Wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.customer_a, cached_balance=10000
        )
        self.wallet_b: Wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.customer_b, cached_balance=5000
        )
        self.other_wallet: Wallet = Wallet.objects.create(
            tenant=self.other_tenant,
            customer=self.other_customer,
            cached_balance=5000,
        )

    def test_successful_transfer_creates_two_linked_transactions(self) -> None:
        debit, credit = transfer(
            self.tenant,
            self.wallet_a.id,
            self.wallet_b.id,
            3000,
            "xfer-1",
            "hash-a",
        )

        self.assertEqual(debit.type, "transfer_debit")
        self.assertEqual(credit.type, "transfer_credit")
        self.assertEqual(debit.amount, 3000)
        self.assertEqual(credit.amount, 3000)
        self.assertEqual(debit.related_transaction_id, credit.id)
        self.assertEqual(credit.related_transaction_id, debit.id)

    def test_successful_transfer_updates_both_balances(self) -> None:
        transfer(
            self.tenant,
            self.wallet_a.id,
            self.wallet_b.id,
            2000,
            "xfer-2",
            "hash-b",
        )
        self.wallet_a.refresh_from_db()
        self.wallet_b.refresh_from_db()
        self.assertEqual(self.wallet_a.cached_balance, 8000)
        self.assertEqual(self.wallet_b.cached_balance, 7000)

    def test_cross_tenant_transfer_fails_with_wallet_not_found(self) -> None:
        txn_count_before = Transaction.objects.count()

        with self.assertRaises(WalletNotFound):
            transfer(
                self.tenant,
                self.wallet_a.id,
                self.other_wallet.id,
                1000,
                "xfer-cross",
                "hash-c",
            )

        self.assertEqual(Transaction.objects.count(), txn_count_before)

    def test_insufficient_funds_changes_nothing(self) -> None:
        balance_a = self.wallet_a.cached_balance
        balance_b = self.wallet_b.cached_balance
        txn_count = Transaction.objects.count()

        with self.assertRaises(InsufficientFunds):
            transfer(
                self.tenant,
                self.wallet_a.id,
                self.wallet_b.id,
                99999,
                "xfer-broke",
                "hash-d",
            )

        self.wallet_a.refresh_from_db()
        self.wallet_b.refresh_from_db()
        self.assertEqual(self.wallet_a.cached_balance, balance_a)
        self.assertEqual(self.wallet_b.cached_balance, balance_b)
        self.assertEqual(Transaction.objects.count(), txn_count)

    def test_invalid_amount_raises(self) -> None:
        with self.assertRaises(InvalidAmount):
            transfer(
                self.tenant,
                self.wallet_a.id,
                self.wallet_b.id,
                0,
                "xfer-zero",
                "hash-e",
            )

    def test_same_wallet_raises(self) -> None:
        with self.assertRaises(SameWalletTransfer):
            transfer(
                self.tenant,
                self.wallet_a.id,
                self.wallet_a.id,
                1000,
                "xfer-self",
                "hash-f",
            )

    def test_idempotent_replay_returns_original_transactions(self) -> None:
        debit1, credit1 = transfer(
            self.tenant,
            self.wallet_a.id,
            self.wallet_b.id,
            1000,
            "xfer-idem",
            "hash-same",
        )
        debit2, credit2 = transfer(
            self.tenant,
            self.wallet_a.id,
            self.wallet_b.id,
            1000,
            "xfer-idem",
            "hash-same",
        )

        self.assertEqual(debit1.id, debit2.id)
        self.assertEqual(credit1.id, credit2.id)
        self.assertEqual(
            Transaction.objects.filter(
                idempotency_key__startswith="xfer-idem"
            ).count(),
            2,
        )

    def test_concurrent_opposite_transfers_no_deadlock(self) -> None:
        self.wallet_a.cached_balance = 10000
        self.wallet_a.save(update_fields=["cached_balance"])
        self.wallet_b.cached_balance = 10000
        self.wallet_b.save(update_fields=["cached_balance"])

        results: list[str] = []
        barrier = threading.Barrier(2, timeout=5)

        def do_transfer(
            from_id: str,
            to_id: str,
            key: str,
            hash_val: str,
        ) -> None:
            try:
                barrier.wait()
                transfer(self.tenant, from_id, to_id, 3000, key, hash_val)
                results.append("success")
            except InsufficientFunds:
                results.append("insufficient")
            except Exception as exc:
                results.append(f"error:{exc}")

        t1 = threading.Thread(
            target=do_transfer,
            args=(self.wallet_a.id, self.wallet_b.id, "race-ab", "h1"),
        )
        t2 = threading.Thread(
            target=do_transfer,
            args=(self.wallet_b.id, self.wallet_a.id, "race-ba", "h2"),
        )
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        for r in results:
            self.assertIn(r, ["success", "insufficient"])

        self.assertIn("success", results)

        self.wallet_a.refresh_from_db()
        self.wallet_b.refresh_from_db()
        total = self.wallet_a.cached_balance + self.wallet_b.cached_balance
        self.assertEqual(total, 20000)
