import uuid
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from tenants.models import Tenant
from wallets.exceptions import (
    CrossTenantTransfer,
    CustomerNotFound,
    IdempotencyKeyConflict,
    InsufficientFunds,
    InvalidAmount,
    SameWalletTransfer,
    WalletNotFound,
    wallet_exception_handler,
)
from wallets.models import Customer, Transaction, TransactionType, Wallet


class BaseAPITestCase(TestCase):
    def setUp(self) -> None:
        self.client: APIClient = APIClient()
        self.tenant: Tenant = Tenant.objects.create(name="Primary Tenant")
        self.auth_headers: dict[str, str] = {
            "HTTP_AUTHORIZATION": f"Api-Key {self.tenant.api_key}"
        }

        self.other_tenant: Tenant = Tenant.objects.create(name="Other Tenant")
        self.other_auth_headers: dict[str, str] = {
            "HTTP_AUTHORIZATION": f"Api-Key {self.other_tenant.api_key}"
        }


class CustomerCreateViewTests(BaseAPITestCase):
    def test_create_customer_and_wallet_success(self) -> None:
        response = self.client.post(
            "/api/customers/",
            data={"username": "alice", "email": "alice@example.com"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["username"], "alice")
        self.assertEqual(response.data["email"], "alice@example.com")
        self.assertIn("wallet_id", response.data)
        self.assertIn("id", response.data)

        customer = Customer.objects.get(id=response.data["id"])
        self.assertEqual(customer.tenant, self.tenant)
        wallet = Wallet.objects.get(id=response.data["wallet_id"])
        self.assertEqual(wallet.customer, customer)
        self.assertEqual(wallet.tenant, self.tenant)
        self.assertEqual(wallet.cached_balance, 0)

    def test_create_customer_duplicate_username_fails(self) -> None:
        self.client.post(
            "/api/customers/",
            data={"username": "bob", "email": "bob@example.com"},
            format="json",
            **self.auth_headers,
        )
        response = self.client.post(
            "/api/customers/",
            data={"username": "bob", "email": "bob2@example.com"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")

    def test_unauthenticated_request_returns_401(self) -> None:
        response = self.client.post(
            "/api/customers/",
            data={"username": "eve", "email": "eve@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"], "not_authenticated")


class WalletDepositViewTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.customer = Customer.objects.create(
            tenant=self.tenant, username="charlie", email="c@c.com"
        )
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.customer, cached_balance=0
        )

        self.other_customer = Customer.objects.create(
            tenant=self.other_tenant, username="david", email="d@d.com"
        )
        self.other_wallet = Wallet.objects.create(
            tenant=self.other_tenant, customer=self.other_customer, cached_balance=0
        )

    def test_deposit_success(self) -> None:
        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 5000, "idempotency_key": "dep-api-1"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["amount"], 5000)
        self.assertEqual(response.data["type"], "deposit")
        self.assertEqual(response.data["status"], "completed")

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 5000)

    def test_deposit_with_idempotency_header(self) -> None:
        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 2500},
            format="json",
            HTTP_IDEMPOTENCY_KEY="dep-header-key",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["amount"], 2500)

    def test_deposit_idempotent_replay(self) -> None:
        res1 = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 1000, "idempotency_key": "dep-replay"},
            format="json",
            **self.auth_headers,
        )
        res2 = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 1000, "idempotency_key": "dep-replay"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["id"], res2.data["id"])

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 1000)

    def test_deposit_idempotency_conflict(self) -> None:
        self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 1000, "idempotency_key": "dep-conflict"},
            format="json",
            **self.auth_headers,
        )
        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 2000, "idempotency_key": "dep-conflict"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"], "idempotency_key_conflict")
        self.assertIn("detail", response.data)

    def test_deposit_invalid_amount(self) -> None:
        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data={"amount": 0, "idempotency_key": "dep-invalid"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "invalid_amount")

    def test_deposit_wrong_tenant_wallet(self) -> None:
        response = self.client.post(
            f"/api/wallets/{self.other_wallet.id}/deposit/",
            data={"amount": 1000, "idempotency_key": "dep-other"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "wallet_not_found")


class WalletWithdrawViewTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.customer = Customer.objects.create(
            tenant=self.tenant, username="edward", email="e@e.com"
        )
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.customer, cached_balance=10000
        )

        self.other_customer = Customer.objects.create(
            tenant=self.other_tenant, username="fiona", email="f@f.com"
        )
        self.other_wallet = Wallet.objects.create(
            tenant=self.other_tenant, customer=self.other_customer, cached_balance=5000
        )

    def test_withdraw_success(self) -> None:
        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/withdraw/",
            data={"amount": 4000, "idempotency_key": "wd-api-1"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["amount"], 4000)
        self.assertEqual(response.data["type"], "withdraw")

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 6000)

    def test_withdraw_insufficient_funds(self) -> None:
        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/withdraw/",
            data={"amount": 99999, "idempotency_key": "wd-broke"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.data["error"], "insufficient_funds")
        self.assertIn("detail", response.data)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.cached_balance, 10000)

    def test_withdraw_invalid_amount(self) -> None:
        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/withdraw/",
            data={"amount": -500, "idempotency_key": "wd-neg"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "invalid_amount")

    def test_withdraw_wrong_tenant_wallet(self) -> None:
        response = self.client.post(
            f"/api/wallets/{self.other_wallet.id}/withdraw/",
            data={"amount": 1000, "idempotency_key": "wd-other"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "wallet_not_found")


class WalletTransferViewTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.sender_cust = Customer.objects.create(
            tenant=self.tenant, username="george", email="g@g.com"
        )
        self.receiver_cust = Customer.objects.create(
            tenant=self.tenant, username="hannah", email="h@h.com"
        )
        self.sender_wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.sender_cust, cached_balance=8000
        )
        self.receiver_wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.receiver_cust, cached_balance=2000
        )

        self.other_cust = Customer.objects.create(
            tenant=self.other_tenant, username="ian", email="i@i.com"
        )
        self.other_wallet = Wallet.objects.create(
            tenant=self.other_tenant, customer=self.other_cust, cached_balance=5000
        )

    def test_transfer_success(self) -> None:
        response = self.client.post(
            "/api/wallets/transfer/",
            data={
                "from_wallet_id": str(self.sender_wallet.id),
                "to_wallet_id": str(self.receiver_wallet.id),
                "amount": 3000,
                "idempotency_key": "xfer-api-1",
            },
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("debit", response.data)
        self.assertIn("credit", response.data)
        self.assertEqual(response.data["debit"]["amount"], 3000)
        self.assertEqual(response.data["credit"]["amount"], 3000)

        self.sender_wallet.refresh_from_db()
        self.receiver_wallet.refresh_from_db()
        self.assertEqual(self.sender_wallet.cached_balance, 5000)
        self.assertEqual(self.receiver_wallet.cached_balance, 5000)

    def test_transfer_insufficient_funds(self) -> None:
        response = self.client.post(
            "/api/wallets/transfer/",
            data={
                "from_wallet_id": str(self.sender_wallet.id),
                "to_wallet_id": str(self.receiver_wallet.id),
                "amount": 90000,
                "idempotency_key": "xfer-api-fail",
            },
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.data["error"], "insufficient_funds")

    def test_transfer_same_wallet(self) -> None:
        response = self.client.post(
            "/api/wallets/transfer/",
            data={
                "from_wallet_id": str(self.sender_wallet.id),
                "to_wallet_id": str(self.sender_wallet.id),
                "amount": 1000,
                "idempotency_key": "xfer-api-self",
            },
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "same_wallet_transfer")

    def test_transfer_cross_tenant_wallet(self) -> None:
        response = self.client.post(
            "/api/wallets/transfer/",
            data={
                "from_wallet_id": str(self.sender_wallet.id),
                "to_wallet_id": str(self.other_wallet.id),
                "amount": 1000,
                "idempotency_key": "xfer-api-cross",
            },
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "wallet_not_found")


class WalletBalanceViewTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.customer = Customer.objects.create(
            tenant=self.tenant, username="jack", email="j@j.com"
        )
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.customer, cached_balance=4500
        )

        self.other_customer = Customer.objects.create(
            tenant=self.other_tenant, username="karen", email="k@k.com"
        )
        self.other_wallet = Wallet.objects.create(
            tenant=self.other_tenant, customer=self.other_customer, cached_balance=1000
        )

    def test_get_balance_success(self) -> None:
        response = self.client.get(
            f"/api/wallets/{self.wallet.id}/balance/",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["wallet_id"], str(self.wallet.id))
        self.assertEqual(response.data["balance"], 4500)
        self.assertEqual(response.data["currency"], "BDT")

    def test_get_balance_wrong_tenant(self) -> None:
        response = self.client.get(
            f"/api/wallets/{self.other_wallet.id}/balance/",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "wallet_not_found")


class WalletTransactionsViewTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.customer = Customer.objects.create(
            tenant=self.tenant, username="leo", email="l@l.com"
        )
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, customer=self.customer, cached_balance=0
        )

    def test_get_transactions_newest_first_and_paginated(self) -> None:
        for i in range(25):
            Transaction.objects.create(
                tenant=self.tenant,
                wallet=self.wallet,
                type=TransactionType.DEPOSIT,
                amount=100 + i,
                idempotency_key=f"hist-key-{i}",
            )

        response = self.client.get(
            f"/api/wallets/{self.wallet.id}/transactions/",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertIn("next", response.data)
        self.assertEqual(len(response.data["results"]), 20)

        results = response.data["results"]
        timestamps = [item["created_at"] for item in results]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_get_transactions_wrong_tenant(self) -> None:
        other_customer = Customer.objects.create(
            tenant=self.other_tenant, username="maya", email="m@m.com"
        )
        other_wallet = Wallet.objects.create(
            tenant=self.other_tenant, customer=other_customer, cached_balance=0
        )
        response = self.client.get(
            f"/api/wallets/{other_wallet.id}/transactions/",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "wallet_not_found")


class ExceptionHandlerUnitTests(TestCase):
    def test_insufficient_funds_mapping(self) -> None:
        resp = wallet_exception_handler(InsufficientFunds("No money"), {})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(resp.data, {"error": "insufficient_funds", "detail": "No money"})

    def test_wallet_not_found_mapping(self) -> None:
        resp = wallet_exception_handler(WalletNotFound("Missing wallet"), {})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data, {"error": "wallet_not_found", "detail": "Missing wallet"})

    def test_customer_not_found_mapping(self) -> None:
        resp = wallet_exception_handler(CustomerNotFound("Missing customer"), {})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data, {"error": "customer_not_found", "detail": "Missing customer"})

    def test_cross_tenant_transfer_mapping(self) -> None:
        resp = wallet_exception_handler(CrossTenantTransfer("Cross tenant"), {})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data, {"error": "cross_tenant_transfer", "detail": "Cross tenant"})

    def test_idempotency_key_conflict_mapping(self) -> None:
        resp = wallet_exception_handler(IdempotencyKeyConflict("Duplicate key"), {})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data, {"error": "idempotency_key_conflict", "detail": "Duplicate key"})

    def test_invalid_amount_mapping(self) -> None:
        resp = wallet_exception_handler(InvalidAmount("Negative"), {})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data, {"error": "invalid_amount", "detail": "Negative"})

    def test_same_wallet_transfer_mapping(self) -> None:
        resp = wallet_exception_handler(SameWalletTransfer("Self"), {})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data, {"error": "same_wallet_transfer", "detail": "Self"})

    def test_drf_validation_error_mapping(self) -> None:
        exc = ValidationError({"amount": ["Must be positive"]})
        resp = wallet_exception_handler(exc, {})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"], "validation_error")
        self.assertIn("amount", resp.data["detail"])

    @patch("wallets.exceptions.logger.exception")
    def test_unhandled_exception_logged_and_returns_none(self, mock_logger) -> None:
        exc = RuntimeError("Unexpected boom")
        resp = wallet_exception_handler(exc, {})
        self.assertIsNone(resp)
        mock_logger.assert_called_once()
