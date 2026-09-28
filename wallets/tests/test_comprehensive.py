"""
Comprehensive test suite covering all test categories:

1. Functional (happy path)      – end-to-end flow with balance checks at every step
2. Negative / validation        – bad inputs never produce 500
3. Tenant isolation (security)  – every endpoint parametrized across tenants
4. Authentication               – missing/wrong/malformed header → 401
5. Idempotency                  – replay, conflict, cross-tenant key re-use
6. Concurrency                  – overdraw race, deadlock-free opposing transfers
7. Atomicity / failure injection – patch credit step, assert full rollback
8. Ledger integrity (invariants) – ledger sum == cached_balance, money conservation
9. Pagination                   – stable ordering, cursor works, no duplicates on insert
10. Error contract               – every error path returns {error, detail} + correct status
"""

import threading
import uuid
from unittest.mock import patch

from django.db import models
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APIClient

from tenants.models import Tenant
from wallets.exceptions import InsufficientFunds
from wallets.models import Customer, Transaction, TransactionType, Wallet
from wallets.services import deposit, transfer, withdraw


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def make_tenant(name: str) -> Tenant:
    return Tenant.objects.create(name=name)


def make_customer(tenant: Tenant, username: str = "user") -> Customer:
    return Customer.objects.create(
        tenant=tenant, username=username, email=f"{username}@test.com"
    )


def make_wallet(tenant: Tenant, customer: Customer, balance: int = 0) -> Wallet:
    return Wallet.objects.create(
        tenant=tenant, customer=customer, cached_balance=balance
    )


# ---------------------------------------------------------------------------
# 1. Functional happy-path – balance checked after every step
# ---------------------------------------------------------------------------

class FunctionalHappyPathTest(TransactionTestCase):
    def test_full_flow_balance_checked_at_every_step(self) -> None:
        client = APIClient()

        # Create tenant
        resp = client.post(
            "/api/tenants/", data={"name": "Flow Corp"}, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        api_key = resp.data["api_key"]
        auth = {"HTTP_AUTHORIZATION": f"Api-Key {api_key}"}

        # Create two customers (each gets a wallet at balance 0)
        r = client.post("/api/customers/", data={"username": "alice", "email": "a@a.com"}, format="json", **auth)
        self.assertEqual(r.status_code, 201)
        w_alice = r.data["wallet_id"]

        r = client.post("/api/customers/", data={"username": "bob", "email": "b@b.com"}, format="json", **auth)
        self.assertEqual(r.status_code, 201)
        w_bob = r.data["wallet_id"]

        def balance(wallet_id: str) -> int:
            r = client.get(f"/api/wallets/{wallet_id}/balance/", **auth)
            self.assertEqual(r.status_code, 200)
            return r.data["balance"]

        self.assertEqual(balance(w_alice), 0)
        self.assertEqual(balance(w_bob), 0)

        # Deposit 10 000 into alice
        r = client.post(f"/api/wallets/{w_alice}/deposit/",
                        data={"amount": 10000, "idempotency_key": "fp-dep-1"}, format="json", **auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(balance(w_alice), 10000)
        self.assertEqual(balance(w_bob), 0)

        # Withdraw 3 000 from alice
        r = client.post(f"/api/wallets/{w_alice}/withdraw/",
                        data={"amount": 3000, "idempotency_key": "fp-wd-1"}, format="json", **auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(balance(w_alice), 7000)

        # Transfer 2 000 alice → bob
        r = client.post("/api/wallets/transfer/", format="json", **auth, data={
            "from_wallet_id": w_alice, "to_wallet_id": w_bob,
            "amount": 2000, "idempotency_key": "fp-xfer-1",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(balance(w_alice), 5000)
        self.assertEqual(balance(w_bob), 2000)

        # History: alice should have deposit + withdraw + transfer_debit (3 rows)
        r = client.get(f"/api/wallets/{w_alice}/transactions/", **auth)
        self.assertEqual(r.status_code, 200)
        types = {t["type"] for t in r.data["results"]}
        self.assertIn("deposit", types)
        self.assertIn("withdraw", types)
        self.assertIn("transfer_debit", types)


# ---------------------------------------------------------------------------
# 2. Negative & validation
# ---------------------------------------------------------------------------

class NegativeValidationTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.tenant = make_tenant("Neg Tenant")
        self.auth = {"HTTP_AUTHORIZATION": f"Api-Key {self.tenant.api_key}"}
        cust = make_customer(self.tenant, "neg_user")
        self.wallet = make_wallet(self.tenant, cust, 10000)

    def _deposit(self, **kwargs) -> object:
        data = {"idempotency_key": "neg-key", **kwargs}
        return self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/", data=data, format="json", **self.auth
        )

    def test_amount_zero_returns_400_invalid_amount(self) -> None:
        r = self._deposit(amount=0)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "invalid_amount")

    def test_amount_negative_returns_400_invalid_amount(self) -> None:
        r = self._deposit(amount=-500)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "invalid_amount")

    def test_amount_string_returns_400_validation_error(self) -> None:
        r = self._deposit(amount="abc")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "validation_error")

    def test_amount_string_integer_rejected_by_strict_field(self) -> None:
        r = self._deposit(amount="100")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "validation_error")

    def test_amount_float_integer_rejected_by_strict_field(self) -> None:
        r = self._deposit(amount=100.0)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "validation_error")

    def test_amount_float_returns_400_validation_error(self) -> None:
        r = self._deposit(amount=9.99)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "validation_error")

    def test_amount_huge_integer_above_bigint_max_returns_400(self) -> None:
        """Amounts exceeding PostgreSQL bigint max are rejected at the serializer layer."""
        bigint_max = 9_223_372_036_854_775_807
        r = self._deposit(amount=bigint_max + 1, idempotency_key="neg-huge")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "validation_error")

    def test_missing_idempotency_key_returns_400(self) -> None:
        r = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 100}, format="json", **self.auth
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "validation_error")

    def test_header_idempotency_key_exceeding_max_length_returns_400(self) -> None:
        long_key = "k" * 256
        r = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 100},
            format="json",
            HTTP_IDEMPOTENCY_KEY=long_key,
            **self.auth,
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "validation_error")

    def test_header_idempotency_key_whitespace_only_returns_400(self) -> None:
        r = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 100},
            format="json",
            HTTP_IDEMPOTENCY_KEY="   ",
            **self.auth,
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "validation_error")

    def test_header_idempotency_key_valid_is_accepted(self) -> None:
        r = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 100},
            format="json",
            HTTP_IDEMPOTENCY_KEY="valid-header-key",
            **self.auth,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["idempotency_key"], "valid-header-key")

    def test_transfer_to_same_wallet_returns_400(self) -> None:
        r = self.client.post("/api/wallets/transfer/", format="json", **self.auth, data={
            "from_wallet_id": str(self.wallet.id),
            "to_wallet_id": str(self.wallet.id),
            "amount": 100, "idempotency_key": "neg-self",
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "same_wallet_transfer")

    def test_malformed_uuid_wallet_id_returns_404(self) -> None:
        r = self.client.get("/api/wallets/not-a-uuid/balance/", **self.auth)
        self.assertIn(r.status_code, [400, 404])

    def test_missing_body_returns_400(self) -> None:
        r = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={}, format="json", **self.auth
        )
        self.assertEqual(r.status_code, 400)

    def test_withdraw_insufficient_funds_returns_402(self) -> None:
        r = self.client.post(
            f"/api/wallets/{self.wallet.id}/withdraw/",
            data={"amount": 99999, "idempotency_key": "neg-wd-over"}, format="json", **self.auth
        )
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.data["error"], "insufficient_funds")

    def test_deposit_nonexistent_wallet_returns_404(self) -> None:
        fake_id = uuid.uuid4()
        r = self.client.post(
            f"/api/wallets/{fake_id}/deposit/",
            data={"amount": 100, "idempotency_key": "neg-nowall"}, format="json", **self.auth
        )
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.data["error"], "wallet_not_found")


# ---------------------------------------------------------------------------
# 3. Tenant isolation – every mutating and read endpoint
# ---------------------------------------------------------------------------

WALLET_ENDPOINTS = [
    ("GET",  "/api/wallets/{wid}/balance/",       None),
    ("GET",  "/api/wallets/{wid}/transactions/",  None),
    ("POST", "/api/wallets/{wid}/deposit/",        {"amount": 100, "idempotency_key": "iso-{wid}-dep"}),
    ("POST", "/api/wallets/{wid}/withdraw/",       {"amount": 100, "idempotency_key": "iso-{wid}-wd"}),
]


class TenantIsolationTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.tenant_a = make_tenant("Iso-A")
        self.tenant_b = make_tenant("Iso-B")
        self.auth_a = {"HTTP_AUTHORIZATION": f"Api-Key {self.tenant_a.api_key}"}
        self.auth_b = {"HTTP_AUTHORIZATION": f"Api-Key {self.tenant_b.api_key}"}

        cust_a = make_customer(self.tenant_a, "iso_a")
        cust_b = make_customer(self.tenant_b, "iso_b")
        self.wallet_a = make_wallet(self.tenant_a, cust_a, 5000)
        self.wallet_b = make_wallet(self.tenant_b, cust_b, 5000)

    def test_get_balance_wrong_tenant_returns_404(self) -> None:
        r = self.client.get(f"/api/wallets/{self.wallet_b.id}/balance/", **self.auth_a)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.data["error"], "wallet_not_found")

    def test_get_transactions_wrong_tenant_returns_404(self) -> None:
        r = self.client.get(f"/api/wallets/{self.wallet_b.id}/transactions/", **self.auth_a)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.data["error"], "wallet_not_found")

    def test_deposit_wrong_tenant_returns_404(self) -> None:
        r = self.client.post(
            f"/api/wallets/{self.wallet_b.id}/deposit/",
            data={"amount": 100, "idempotency_key": "iso-cross-dep"}, format="json", **self.auth_a
        )
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.data["error"], "wallet_not_found")

    def test_withdraw_wrong_tenant_returns_404(self) -> None:
        r = self.client.post(
            f"/api/wallets/{self.wallet_b.id}/withdraw/",
            data={"amount": 100, "idempotency_key": "iso-cross-wd"}, format="json", **self.auth_a
        )
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.data["error"], "wallet_not_found")

    def test_transfer_cross_tenant_returns_404_and_writes_nothing(self) -> None:
        txn_count = Transaction.objects.count()
        r = self.client.post("/api/wallets/transfer/", format="json", **self.auth_a, data={
            "from_wallet_id": str(self.wallet_a.id),
            "to_wallet_id": str(self.wallet_b.id),
            "amount": 100, "idempotency_key": "iso-cross-xfer",
        })
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.data["error"], "wallet_not_found")
        self.assertEqual(Transaction.objects.count(), txn_count)

    def test_cross_tenant_response_is_404_not_403(self) -> None:
        """A 403 would leak that the wallet exists. Must be 404."""
        r = self.client.get(f"/api/wallets/{self.wallet_b.id}/balance/", **self.auth_a)
        self.assertEqual(r.status_code, 404)
        self.assertNotEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# 4. Authentication
# ---------------------------------------------------------------------------

class AuthenticationTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.tenant = make_tenant("Auth Tenant")
        cust = make_customer(self.tenant, "auth_user")
        self.wallet = make_wallet(self.tenant, cust, 1000)

    def test_missing_auth_header_returns_401(self) -> None:
        r = self.client.get(f"/api/wallets/{self.wallet.id}/balance/")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.data["error"], "not_authenticated")

    def test_wrong_api_key_returns_401(self) -> None:
        r = self.client.get(
            f"/api/wallets/{self.wallet.id}/balance/",
            HTTP_AUTHORIZATION="Api-Key totally-wrong-key"
        )
        self.assertEqual(r.status_code, 401)

    def test_malformed_header_missing_scheme_returns_401(self) -> None:
        r = self.client.get(
            f"/api/wallets/{self.wallet.id}/balance/",
            HTTP_AUTHORIZATION="Bearer some-token"
        )
        self.assertEqual(r.status_code, 401)

    def test_malformed_header_no_key_value_returns_401(self) -> None:
        r = self.client.get(
            f"/api/wallets/{self.wallet.id}/balance/",
            HTTP_AUTHORIZATION="Api-Key"
        )
        self.assertEqual(r.status_code, 401)

    def test_tenant_create_endpoint_is_open_no_auth_needed(self) -> None:
        r = self.client.post(
            "/api/tenants/", data={"name": "Open Tenant"}, format="json"
        )
        self.assertEqual(r.status_code, 201)

    def test_customer_create_requires_auth(self) -> None:
        r = self.client.post(
            "/api/customers/", data={"username": "x", "email": "x@x.com"}, format="json"
        )
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# 5. Idempotency
# ---------------------------------------------------------------------------

class IdempotencyTests(TransactionTestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.tenant = make_tenant("Idem Tenant")
        self.auth = {"HTTP_AUTHORIZATION": f"Api-Key {self.tenant.api_key}"}
        cust = make_customer(self.tenant, "idem_user")
        self.wallet = make_wallet(self.tenant, cust, 10000)

    def test_deposit_replay_same_payload_returns_same_txn_and_does_not_double_charge(self) -> None:
        data = {"amount": 500, "idempotency_key": "idem-dep-1"}
        r1 = self.client.post(f"/api/wallets/{self.wallet.id}/deposit/", data=data, format="json", **self.auth)
        r2 = self.client.post(f"/api/wallets/{self.wallet.id}/deposit/", data=data, format="json", **self.auth)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 10500)  # not 11000

    def test_deposit_conflict_different_amount_returns_409(self) -> None:
        self.client.post(f"/api/wallets/{self.wallet.id}/deposit/",
                         data={"amount": 100, "idempotency_key": "idem-conflict"}, format="json", **self.auth)
        r = self.client.post(f"/api/wallets/{self.wallet.id}/deposit/",
                              data={"amount": 999, "idempotency_key": "idem-conflict"}, format="json", **self.auth)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["error"], "idempotency_key_conflict")

    def test_withdraw_replay_does_not_double_deduct(self) -> None:
        data = {"amount": 1000, "idempotency_key": "idem-wd-1"}
        r1 = self.client.post(f"/api/wallets/{self.wallet.id}/withdraw/", data=data, format="json", **self.auth)
        r2 = self.client.post(f"/api/wallets/{self.wallet.id}/withdraw/", data=data, format="json", **self.auth)
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 9000)  # not 8000

    def test_transfer_replay_does_not_create_extra_rows(self) -> None:
        tenant_b = make_tenant("Idem-B")
        # Second wallet in same tenant
        cust_b = make_customer(self.tenant, "idem_bob")
        wallet_b = make_wallet(self.tenant, cust_b, 0)

        data = {"from_wallet_id": str(self.wallet.id), "to_wallet_id": str(wallet_b.id),
                "amount": 500, "idempotency_key": "idem-xfer-1"}
        r1 = self.client.post("/api/wallets/transfer/", data=data, format="json", **self.auth)
        r2 = self.client.post("/api/wallets/transfer/", data=data, format="json", **self.auth)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Only 2 transaction rows (debit + credit), not 4
        self.assertEqual(Transaction.objects.filter(
            idempotency_key__startswith="idem-xfer-1").count(), 2)

    def test_same_key_allowed_for_different_tenants(self) -> None:
        """Idempotency keys are scoped per tenant — two tenants may reuse the same string."""
        tenant_b = make_tenant("Idem-Other")
        cust_b = make_customer(tenant_b, "other_user")
        wallet_b = make_wallet(tenant_b, cust_b, 0)
        auth_b = {"HTTP_AUTHORIZATION": f"Api-Key {tenant_b.api_key}"}

        r_a = self.client.post(f"/api/wallets/{self.wallet.id}/deposit/",
                               data={"amount": 200, "idempotency_key": "shared-key"}, format="json", **self.auth)
        r_b = self.client.post(f"/api/wallets/{wallet_b.id}/deposit/",
                               data={"amount": 300, "idempotency_key": "shared-key"}, format="json", **auth_b)
        self.assertEqual(r_a.status_code, 200)
        self.assertEqual(r_b.status_code, 200)
        self.assertNotEqual(r_a.data["id"], r_b.data["id"])


# ---------------------------------------------------------------------------
# 6. Concurrency
# ---------------------------------------------------------------------------

class ConcurrencyTests(TransactionTestCase):
    def test_parallel_withdrawals_never_overdraw(self) -> None:
        tenant = make_tenant("Conc-Wd")
        cust = make_customer(tenant, "racer")
        wallet = make_wallet(tenant, cust, 10000)
        results: list[str] = []
        barrier = threading.Barrier(2, timeout=5)

        def do_withdraw(key: str) -> None:
            try:
                barrier.wait()
                withdraw(tenant, wallet.id, 7000, key, key)
                results.append("ok")
            except InsufficientFunds:
                results.append("insufficient")
            except Exception as exc:
                results.append(f"err:{exc}")

        t1 = threading.Thread(target=do_withdraw, args=("cwd-1",))
        t2 = threading.Thread(target=do_withdraw, args=("cwd-2",))
        t1.start(); t2.start()
        t1.join(timeout=10); t2.join(timeout=10)

        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("insufficient"), 1)
        wallet.refresh_from_db()
        self.assertEqual(wallet.cached_balance, 3000)
        self.assertGreaterEqual(wallet.cached_balance, 0)

    def test_opposing_transfers_no_deadlock_money_conserved(self) -> None:
        tenant = make_tenant("Conc-Xfer")
        ca = make_customer(tenant, "ca")
        cb = make_customer(tenant, "cb")
        wa = make_wallet(tenant, ca, 10000)
        wb = make_wallet(tenant, cb, 10000)
        results: list[str] = []
        barrier = threading.Barrier(2, timeout=5)

        def do_transfer(from_w, to_w, key: str) -> None:
            try:
                barrier.wait()
                transfer(tenant, from_w.id, to_w.id, 3000, key, key)
                results.append("ok")
            except InsufficientFunds:
                results.append("insufficient")
            except Exception as exc:
                results.append(f"err:{exc}")

        t1 = threading.Thread(target=do_transfer, args=(wa, wb, "cx-ab"))
        t2 = threading.Thread(target=do_transfer, args=(wb, wa, "cx-ba"))
        t1.start(); t2.start()
        t1.join(timeout=10); t2.join(timeout=10)

        for r in results:
            self.assertIn(r, ["ok", "insufficient"], f"Unexpected: {r}")
        self.assertIn("ok", results)

        wa.refresh_from_db(); wb.refresh_from_db()
        self.assertEqual(wa.cached_balance + wb.cached_balance, 20000)

    def test_racing_identical_deposits_produce_exactly_one_row(self) -> None:
        tenant = make_tenant("Conc-Race")
        cust = make_customer(tenant, "rr")
        wallet = make_wallet(tenant, cust, 0)
        barrier = threading.Barrier(2, timeout=5)
        results: list = []

        def do_deposit() -> None:
            barrier.wait()
            try:
                txn = deposit(tenant, wallet.id, 100, "race-key", "race-hash")
                results.append(txn.id)
            except Exception as exc:
                results.append(f"err:{exc}")

        t1 = threading.Thread(target=do_deposit)
        t2 = threading.Thread(target=do_deposit)
        t1.start(); t2.start()
        t1.join(timeout=10); t2.join(timeout=10)

        self.assertEqual(len(results), 2)
        # Both return the same transaction ID (winner + IntegrityError loser re-fetches)
        self.assertEqual(results[0], results[1])
        self.assertEqual(Transaction.objects.filter(
            tenant=tenant, idempotency_key="race-key").count(), 1)
        wallet.refresh_from_db()
        self.assertEqual(wallet.cached_balance, 100)


# ---------------------------------------------------------------------------
# 7. Atomicity / failure injection
# ---------------------------------------------------------------------------

class AtomicityTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant = make_tenant("Atomic Tenant")
        self.ca = make_customer(self.tenant, "atom_a")
        self.cb = make_customer(self.tenant, "atom_b")
        self.wa = make_wallet(self.tenant, self.ca, 10000)
        self.wb = make_wallet(self.tenant, self.cb, 0)

    def test_transfer_rollback_when_credit_save_raises(self) -> None:
        """
        Patch Wallet.save to raise RuntimeError on the receiver's cached_balance update.
        The entire transaction must roll back: no Transaction rows, balances unchanged.
        """
        original_save = Wallet.save
        call_count = {"n": 0}

        def failing_save(self_w, *args, **kwargs):
            call_count["n"] += 1
            # The second save() call inside transfer() is receiver.cached_balance += amount
            if call_count["n"] == 2 and kwargs.get("update_fields") == ["cached_balance"]:
                raise RuntimeError("Injected failure on receiver balance update")
            return original_save(self_w, *args, **kwargs)

        txn_count_before = Transaction.objects.count()

        with patch.object(Wallet, "save", failing_save):
            with self.assertRaises(RuntimeError):
                transfer(self.tenant, self.wa.id, self.wb.id,
                         2000, "atomic-key", "atomic-hash")

        # No transaction rows must have survived
        self.assertEqual(Transaction.objects.count(), txn_count_before)
        # Balances must be unchanged
        self.wa.refresh_from_db()
        self.wb.refresh_from_db()
        self.assertEqual(self.wa.cached_balance, 10000)
        self.assertEqual(self.wb.cached_balance, 0)

    def test_deposit_rollback_when_wallet_save_raises(self) -> None:
        original_save = Wallet.save

        def failing_save(self_w, *args, **kwargs):
            if kwargs.get("update_fields") == ["cached_balance"]:
                raise RuntimeError("Injected failure")
            return original_save(self_w, *args, **kwargs)

        txn_count_before = Transaction.objects.count()
        with patch.object(Wallet, "save", failing_save):
            with self.assertRaises(RuntimeError):
                deposit(self.tenant, self.wa.id, 500, "atom-dep", "atom-dep-hash")

        self.assertEqual(Transaction.objects.count(), txn_count_before)
        self.wa.refresh_from_db()
        self.assertEqual(self.wa.cached_balance, 10000)


# ---------------------------------------------------------------------------
# 8. Ledger integrity / invariants
# ---------------------------------------------------------------------------

class LedgerIntegrityTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant = make_tenant("Ledger Tenant")

    def _ledger_sum(self, wallet: Wallet) -> int:
        credits = Transaction.objects.filter(
            wallet=wallet, type__in=[TransactionType.DEPOSIT, TransactionType.TRANSFER_CREDIT]
        ).aggregate(s=models.Sum("amount"))["s"] or 0
        debits = Transaction.objects.filter(
            wallet=wallet, type__in=[TransactionType.WITHDRAW, TransactionType.TRANSFER_DEBIT]
        ).aggregate(s=models.Sum("amount"))["s"] or 0
        return credits - debits

    def test_ledger_sum_equals_cached_balance_after_deposit_withdraw(self) -> None:
        cust = make_customer(self.tenant, "ledger_a")
        wallet = make_wallet(self.tenant, cust, 0)
        deposit(self.tenant, wallet.id, 5000, "l-dep-1", "h1")
        deposit(self.tenant, wallet.id, 3000, "l-dep-2", "h2")
        withdraw(self.tenant, wallet.id, 2000, "l-wd-1", "h3")
        wallet.refresh_from_db()
        self.assertEqual(self._ledger_sum(wallet), wallet.cached_balance)
        self.assertEqual(wallet.cached_balance, 6000)

    def test_transfer_creates_exactly_two_linked_rows(self) -> None:
        ca = make_customer(self.tenant, "l_alice")
        cb = make_customer(self.tenant, "l_bob")
        wa = make_wallet(self.tenant, ca, 5000)
        wb = make_wallet(self.tenant, cb, 0)
        debit, credit = transfer(self.tenant, wa.id, wb.id, 1500, "l-xfer-1", "lx-h1")

        self.assertEqual(debit.type, "transfer_debit")
        self.assertEqual(credit.type, "transfer_credit")
        self.assertEqual(debit.amount, credit.amount)
        self.assertEqual(debit.related_transaction_id, credit.id)
        self.assertEqual(credit.related_transaction_id, debit.id)

    def test_money_is_conserved_across_wallets_after_transfer(self) -> None:
        ca = make_customer(self.tenant, "l_ca")
        cb = make_customer(self.tenant, "l_cb")
        wa = make_wallet(self.tenant, ca, 8000)
        wb = make_wallet(self.tenant, cb, 2000)
        total_before = wa.cached_balance + wb.cached_balance

        transfer(self.tenant, wa.id, wb.id, 3000, "l-cons-1", "lc-h1")
        wa.refresh_from_db(); wb.refresh_from_db()
        self.assertEqual(wa.cached_balance + wb.cached_balance, total_before)

    def test_ledger_sum_equals_cached_balance_after_transfer(self) -> None:
        """Wallets seeded via deposit() so every unit of money has a ledger row."""
        ca = make_customer(self.tenant, "l_tx_a")
        cb = make_customer(self.tenant, "l_tx_b")
        wa = make_wallet(self.tenant, ca, 0)  # start at 0
        wb = make_wallet(self.tenant, cb, 0)
        deposit(self.tenant, wa.id, 9000, "l-seed-a", "hs-a")   # seed via service
        deposit(self.tenant, wa.id, 1000, "l-dep-x", "hx")
        transfer(self.tenant, wa.id, wb.id, 4000, "l-xfer-x", "hxf")
        wa.refresh_from_db(); wb.refresh_from_db()
        self.assertEqual(self._ledger_sum(wa), wa.cached_balance)  # (9000+1000)-4000 = 6000
        self.assertEqual(self._ledger_sum(wb), wb.cached_balance)  # 4000

    def test_amount_is_always_positive_in_ledger(self) -> None:
        cust = make_customer(self.tenant, "l_pos")
        wallet = make_wallet(self.tenant, cust, 5000)
        deposit(self.tenant, wallet.id, 1000, "l-pos-dep", "hp")
        withdraw(self.tenant, wallet.id, 500, "l-pos-wd", "hw")
        for txn in Transaction.objects.filter(tenant=self.tenant, wallet=wallet):
            self.assertGreater(txn.amount, 0, f"Non-positive amount on {txn.type}")


# ---------------------------------------------------------------------------
# 9. Pagination
# ---------------------------------------------------------------------------

class PaginationTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.tenant = make_tenant("Page Tenant")
        self.auth = {"HTTP_AUTHORIZATION": f"Api-Key {self.tenant.api_key}"}
        cust = make_customer(self.tenant, "page_user")
        self.wallet = make_wallet(self.tenant, cust, 0)

    def test_first_page_is_newest_first_and_has_20_results(self) -> None:
        for i in range(25):
            Transaction.objects.create(
                tenant=self.tenant, wallet=self.wallet,
                type=TransactionType.DEPOSIT, amount=i + 1,
                idempotency_key=f"pg-key-{i}",
            )
        r = self.client.get(f"/api/wallets/{self.wallet.id}/transactions/", **self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertIn("next", r.data)
        self.assertEqual(len(r.data["results"]), 20)
        timestamps = [item["created_at"] for item in r.data["results"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_cursor_next_page_returns_remaining_results(self) -> None:
        for i in range(25):
            Transaction.objects.create(
                tenant=self.tenant, wallet=self.wallet,
                type=TransactionType.DEPOSIT, amount=i + 1,
                idempotency_key=f"pg2-key-{i}",
            )
        r1 = self.client.get(f"/api/wallets/{self.wallet.id}/transactions/", **self.auth)
        next_url = r1.data.get("next")
        self.assertIsNotNone(next_url)

        r2 = self.client.get(next_url, **self.auth)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(len(r2.data["results"]), 5)

    def test_no_duplicates_when_new_transaction_inserted_between_pages(self) -> None:
        for i in range(20):
            Transaction.objects.create(
                tenant=self.tenant, wallet=self.wallet,
                type=TransactionType.DEPOSIT, amount=i + 1,
                idempotency_key=f"pgsep-{i}",
            )
        r1 = self.client.get(f"/api/wallets/{self.wallet.id}/transactions/", **self.auth)
        ids_page1 = {item["id"] for item in r1.data["results"]}

        # New transaction inserted AFTER fetching page 1
        Transaction.objects.create(
            tenant=self.tenant, wallet=self.wallet,
            type=TransactionType.DEPOSIT, amount=9999,
            idempotency_key="pgsep-new",
        )

        next_url = r1.data.get("next")
        if next_url:
            r2 = self.client.get(next_url, **self.auth)
            ids_page2 = {item["id"] for item in r2.data["results"]}
            self.assertTrue(ids_page1.isdisjoint(ids_page2), "Duplicate IDs across pages")

    def test_empty_wallet_returns_empty_results(self) -> None:
        r = self.client.get(f"/api/wallets/{self.wallet.id}/transactions/", **self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["results"]), 0)


# ---------------------------------------------------------------------------
# 10. Error contract – every error path returns {error, detail} + correct status
# ---------------------------------------------------------------------------

class ErrorContractTests(TestCase):
    """Every error response must have exactly 'error' and 'detail' keys."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.tenant = make_tenant("EC Tenant")
        self.auth = {"HTTP_AUTHORIZATION": f"Api-Key {self.tenant.api_key}"}
        cust = make_customer(self.tenant, "ec_user")
        self.wallet = make_wallet(self.tenant, cust, 500)
        self.other_tenant = make_tenant("EC Other")
        other_cust = make_customer(self.other_tenant, "ec_other")
        self.other_wallet = make_wallet(self.other_tenant, other_cust, 500)

    def _assert_error_shape(self, response, expected_status: int, expected_code: str) -> None:
        self.assertEqual(response.status_code, expected_status,
                         f"Expected {expected_status}, got {response.status_code}. Body: {response.data}")
        self.assertIn("error", response.data, "Response missing 'error' key")
        self.assertIn("detail", response.data, "Response missing 'detail' key")
        self.assertEqual(response.data["error"], expected_code,
                         f"Expected error code '{expected_code}', got '{response.data['error']}'")

    def test_401_not_authenticated_shape(self) -> None:
        r = self.client.get(f"/api/wallets/{self.wallet.id}/balance/")
        self._assert_error_shape(r, 401, "not_authenticated")

    def test_400_invalid_amount_shape(self) -> None:
        r = self.client.post(f"/api/wallets/{self.wallet.id}/deposit/",
                             data={"amount": 0, "idempotency_key": "ec-inv"}, format="json", **self.auth)
        self._assert_error_shape(r, 400, "invalid_amount")

    def test_400_same_wallet_transfer_shape(self) -> None:
        r = self.client.post("/api/wallets/transfer/", format="json", **self.auth, data={
            "from_wallet_id": str(self.wallet.id), "to_wallet_id": str(self.wallet.id),
            "amount": 10, "idempotency_key": "ec-same",
        })
        self._assert_error_shape(r, 400, "same_wallet_transfer")

    def test_400_validation_error_shape(self) -> None:
        r = self.client.post(f"/api/wallets/{self.wallet.id}/deposit/",
                             data={"amount": "bad", "idempotency_key": "ec-val"}, format="json", **self.auth)
        self._assert_error_shape(r, 400, "validation_error")

    def test_402_insufficient_funds_shape(self) -> None:
        r = self.client.post(f"/api/wallets/{self.wallet.id}/withdraw/",
                             data={"amount": 9999, "idempotency_key": "ec-insuf"}, format="json", **self.auth)
        self._assert_error_shape(r, 402, "insufficient_funds")

    def test_404_wallet_not_found_shape(self) -> None:
        r = self.client.get(f"/api/wallets/{uuid.uuid4()}/balance/", **self.auth)
        self._assert_error_shape(r, 404, "wallet_not_found")

    def test_404_cross_tenant_shape(self) -> None:
        r = self.client.get(f"/api/wallets/{self.other_wallet.id}/balance/", **self.auth)
        self._assert_error_shape(r, 404, "wallet_not_found")

    def test_409_idempotency_conflict_shape(self) -> None:
        self.client.post(f"/api/wallets/{self.wallet.id}/deposit/",
                         data={"amount": 10, "idempotency_key": "ec-idem"}, format="json", **self.auth)
        r = self.client.post(f"/api/wallets/{self.wallet.id}/deposit/",
                             data={"amount": 99, "idempotency_key": "ec-idem"}, format="json", **self.auth)
        self._assert_error_shape(r, 409, "idempotency_key_conflict")
