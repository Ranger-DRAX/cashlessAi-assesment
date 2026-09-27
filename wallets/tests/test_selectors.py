import uuid

from django.test import TestCase

from tenants.models import Tenant
from wallets.exceptions import CustomerNotFound, WalletNotFound
from wallets.models import Customer, Transaction, TransactionType, Wallet
from wallets.selectors import (
    get_balance,
    get_customer_for_tenant,
    get_transaction_history,
    get_wallet_for_tenant,
)


class GetWalletForTenantTests(TestCase):
    def setUp(self) -> None:
        self.tenant_a: Tenant = Tenant.objects.create(name="Tenant A")
        self.tenant_b: Tenant = Tenant.objects.create(name="Tenant B")

        self.customer_a: Customer = Customer.objects.create(
            tenant=self.tenant_a, username="alice", email="alice@a.com"
        )
        self.customer_b: Customer = Customer.objects.create(
            tenant=self.tenant_b, username="bob", email="bob@b.com"
        )

        self.wallet_a: Wallet = Wallet.objects.create(
            tenant=self.tenant_a, customer=self.customer_a
        )
        self.wallet_b: Wallet = Wallet.objects.create(
            tenant=self.tenant_b, customer=self.customer_b
        )

    def test_returns_wallet_for_own_tenant(self) -> None:
        wallet = get_wallet_for_tenant(self.tenant_a, self.wallet_a.id)
        self.assertEqual(wallet.id, self.wallet_a.id)

    def test_raises_wallet_not_found_for_other_tenant(self) -> None:
        with self.assertRaises(WalletNotFound):
            get_wallet_for_tenant(self.tenant_a, self.wallet_b.id)

    def test_raises_wallet_not_found_for_nonexistent_id(self) -> None:
        with self.assertRaises(WalletNotFound):
            get_wallet_for_tenant(self.tenant_a, uuid.uuid4())


class GetBalanceTests(TestCase):
    def test_returns_cached_balance(self) -> None:
        tenant: Tenant = Tenant.objects.create(name="Balance Tenant")
        customer: Customer = Customer.objects.create(
            tenant=tenant, username="charlie", email="c@c.com"
        )
        wallet: Wallet = Wallet.objects.create(
            tenant=tenant, customer=customer, cached_balance=5000
        )
        self.assertEqual(get_balance(wallet), 5000)


class GetTransactionHistoryTests(TestCase):
    def setUp(self) -> None:
        self.tenant: Tenant = Tenant.objects.create(name="History Tenant")
        self.customer: Customer = Customer.objects.create(
            tenant=self.tenant, username="dave", email="d@d.com"
        )
        self.wallet: Wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.customer
        )
        self.txn_1: Transaction = Transaction.objects.create(
            tenant=self.tenant,
            wallet=self.wallet,
            type=TransactionType.DEPOSIT,
            amount=1000,
            idempotency_key="key-1",
        )
        self.txn_2: Transaction = Transaction.objects.create(
            tenant=self.tenant,
            wallet=self.wallet,
            type=TransactionType.WITHDRAW,
            amount=500,
            idempotency_key="key-2",
        )

    def test_returns_transactions_for_wallet(self) -> None:
        qs = get_transaction_history(self.tenant, self.wallet)
        self.assertEqual(qs.count(), 2)

    def test_excludes_other_tenants_transactions(self) -> None:
        other_tenant: Tenant = Tenant.objects.create(name="Other")
        qs = get_transaction_history(other_tenant, self.wallet)
        self.assertEqual(qs.count(), 0)

    def test_ordered_newest_first(self) -> None:
        qs = get_transaction_history(self.tenant, self.wallet)
        timestamps = list(qs.values_list("created_at", flat=True))
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))


class GetCustomerForTenantTests(TestCase):
    def setUp(self) -> None:
        self.tenant_a: Tenant = Tenant.objects.create(name="Tenant A")
        self.tenant_b: Tenant = Tenant.objects.create(name="Tenant B")
        self.customer_a: Customer = Customer.objects.create(
            tenant=self.tenant_a, username="eve", email="e@e.com"
        )
        self.customer_b: Customer = Customer.objects.create(
            tenant=self.tenant_b, username="frank", email="f@f.com"
        )

    def test_returns_customer_for_own_tenant(self) -> None:
        customer = get_customer_for_tenant(self.tenant_a, self.customer_a.id)
        self.assertEqual(customer.id, self.customer_a.id)

    def test_raises_customer_not_found_for_other_tenant(self) -> None:
        with self.assertRaises(CustomerNotFound):
            get_customer_for_tenant(self.tenant_a, self.customer_b.id)

    def test_raises_customer_not_found_for_nonexistent_id(self) -> None:
        with self.assertRaises(CustomerNotFound):
            get_customer_for_tenant(self.tenant_a, uuid.uuid4())
