import threading

from django.test import TransactionTestCase
from rest_framework import status
from rest_framework.test import APIClient

from tenants.models import Tenant
from wallets.exceptions import InsufficientFunds
from wallets.models import Customer, Wallet


class EndToEndHappyPathTest(TransactionTestCase):
    """Full flow: create tenant → customer → deposit → withdraw → transfer → balance → history."""

    def setUp(self) -> None:
        self.client: APIClient = APIClient()

    def _auth(self, api_key: str) -> dict[str, str]:
        return {"HTTP_AUTHORIZATION": f"Api-Key {api_key}"}

    def test_full_wallet_flow(self) -> None:
        # 1. Create tenant
        resp = self.client.post(
            "/api/tenants/",
            data={"name": "E2E Corp"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        api_key = resp.data["api_key"]
        auth = self._auth(api_key)

        # 2. Create sender customer + wallet
        resp = self.client.post(
            "/api/customers/",
            data={"username": "alice", "email": "alice@e2e.com"},
            format="json",
            **auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        sender_wallet_id = resp.data["wallet_id"]

        # 3. Create receiver customer + wallet
        resp = self.client.post(
            "/api/customers/",
            data={"username": "bob", "email": "bob@e2e.com"},
            format="json",
            **auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        receiver_wallet_id = resp.data["wallet_id"]

        # 4. Deposit into sender's wallet
        resp = self.client.post(
            f"/api/wallets/{sender_wallet_id}/deposit/",
            data={"amount": 10000, "idempotency_key": "e2e-dep-1"},
            format="json",
            **auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["amount"], 10000)
        self.assertEqual(resp.data["type"], "deposit")

        # 5. Withdraw from sender's wallet
        resp = self.client.post(
            f"/api/wallets/{sender_wallet_id}/withdraw/",
            data={"amount": 2000, "idempotency_key": "e2e-wd-1"},
            format="json",
            **auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["amount"], 2000)
        self.assertEqual(resp.data["type"], "withdraw")

        # 6. Transfer from sender to receiver
        resp = self.client.post(
            "/api/wallets/transfer/",
            data={
                "from_wallet_id": str(sender_wallet_id),
                "to_wallet_id": str(receiver_wallet_id),
                "amount": 3000,
                "idempotency_key": "e2e-xfer-1",
            },
            format="json",
            **auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("debit", resp.data)
        self.assertIn("credit", resp.data)
        self.assertEqual(resp.data["debit"]["amount"], 3000)

        # 7. Check sender balance: 10000 - 2000 - 3000 = 5000
        resp = self.client.get(f"/api/wallets/{sender_wallet_id}/balance/", **auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["balance"], 5000)

        # 8. Check receiver balance: 0 + 3000 = 3000
        resp = self.client.get(f"/api/wallets/{receiver_wallet_id}/balance/", **auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["balance"], 3000)

        # 9. Check sender transaction history (deposit + withdraw + transfer_debit = 3 txns)
        resp = self.client.get(f"/api/wallets/{sender_wallet_id}/transactions/", **auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data["results"]
        self.assertEqual(len(results), 3)
        types = {t["type"] for t in results}
        self.assertIn("deposit", types)
        self.assertIn("withdraw", types)
        self.assertIn("transfer_debit", types)

        # 10. Check receiver transaction history (transfer_credit = 1 txn)
        resp = self.client.get(f"/api/wallets/{receiver_wallet_id}/transactions/", **auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["type"], "transfer_credit")


class TenantIsolationE2ETests(TransactionTestCase):
    """Prove tenant isolation at the API level: 404 on cross-tenant reads."""

    def setUp(self) -> None:
        self.client: APIClient = APIClient()
        self.tenant_a = Tenant.objects.create(name="Tenant A")
        self.tenant_b = Tenant.objects.create(name="Tenant B")

        self.auth_a = {"HTTP_AUTHORIZATION": f"Api-Key {self.tenant_a.api_key}"}
        self.auth_b = {"HTTP_AUTHORIZATION": f"Api-Key {self.tenant_b.api_key}"}

        cust_a = Customer.objects.create(tenant=self.tenant_a, username="a_user", email="a@a.com")
        cust_b = Customer.objects.create(tenant=self.tenant_b, username="b_user", email="b@b.com")
        self.wallet_a = Wallet.objects.create(tenant=self.tenant_a, customer=cust_a, cached_balance=5000)
        self.wallet_b = Wallet.objects.create(tenant=self.tenant_b, customer=cust_b, cached_balance=5000)

    def test_tenant_a_cannot_read_tenant_b_balance(self) -> None:
        resp = self.client.get(f"/api/wallets/{self.wallet_b.id}/balance/", **self.auth_a)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"], "wallet_not_found")

    def test_tenant_a_cannot_read_tenant_b_transaction_history(self) -> None:
        resp = self.client.get(f"/api/wallets/{self.wallet_b.id}/transactions/", **self.auth_a)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"], "wallet_not_found")

    def test_transfer_between_different_tenant_wallets_is_rejected(self) -> None:
        txn_count_before = __import__("wallets.models", fromlist=["Transaction"]).Transaction.objects.count()
        resp = self.client.post(
            "/api/wallets/transfer/",
            data={
                "from_wallet_id": str(self.wallet_a.id),
                "to_wallet_id": str(self.wallet_b.id),
                "amount": 1000,
                "idempotency_key": "iso-xfer-1",
            },
            format="json",
            **self.auth_a,
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"], "wallet_not_found")

        from wallets.models import Transaction
        self.assertEqual(Transaction.objects.count(), txn_count_before)

    def test_deposit_idempotency_same_payload_returns_same_result(self) -> None:
        resp1 = self.client.post(
            f"/api/wallets/{self.wallet_a.id}/deposit/",
            data={"amount": 500, "idempotency_key": "iso-dep-idem"},
            format="json",
            **self.auth_a,
        )
        resp2 = self.client.post(
            f"/api/wallets/{self.wallet_a.id}/deposit/",
            data={"amount": 500, "idempotency_key": "iso-dep-idem"},
            format="json",
            **self.auth_a,
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data["id"], resp2.data["id"])
        self.wallet_a.refresh_from_db()
        self.assertEqual(self.wallet_a.cached_balance, 5500)

    def test_deposit_idempotency_different_payload_returns_409(self) -> None:
        self.client.post(
            f"/api/wallets/{self.wallet_a.id}/deposit/",
            data={"amount": 100, "idempotency_key": "iso-dep-conflict"},
            format="json",
            **self.auth_a,
        )
        resp = self.client.post(
            f"/api/wallets/{self.wallet_a.id}/deposit/",
            data={"amount": 999, "idempotency_key": "iso-dep-conflict"},
            format="json",
            **self.auth_a,
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"], "idempotency_key_conflict")

    def test_withdraw_more_than_balance_rejected_and_unchanged(self) -> None:
        original_balance = self.wallet_a.cached_balance
        resp = self.client.post(
            f"/api/wallets/{self.wallet_a.id}/withdraw/",
            data={"amount": original_balance + 1, "idempotency_key": "iso-wd-overdraft"},
            format="json",
            **self.auth_a,
        )
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(resp.data["error"], "insufficient_funds")
        self.wallet_a.refresh_from_db()
        self.assertEqual(self.wallet_a.cached_balance, original_balance)

        from wallets.models import Transaction
        self.assertEqual(Transaction.objects.filter(wallet=self.wallet_a).count(), 0)


class ConcurrentWithdrawE2ETests(TransactionTestCase):
    """API-level concurrency test: two concurrent withdrawals never overdraw the wallet."""

    def test_concurrent_withdrawals_via_service_never_overdraw(self) -> None:
        from wallets.services import withdraw

        tenant = Tenant.objects.create(name="Concurrent Tenant")
        cust = Customer.objects.create(tenant=tenant, username="racer", email="r@r.com")
        wallet = Wallet.objects.create(tenant=tenant, customer=cust, cached_balance=10000)

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

        t1 = threading.Thread(target=do_withdraw, args=("conc-wd-1", "h1"))
        t2 = threading.Thread(target=do_withdraw, args=("conc-wd-2", "h2"))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(len(results), 2)
        self.assertEqual(results.count("success"), 1)
        self.assertEqual(results.count("insufficient"), 1)

        wallet.refresh_from_db()
        self.assertEqual(wallet.cached_balance, 3000)
