from __future__ import annotations

from uuid import UUID

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, inline_serializer

from tenants.authentication import TenantPrincipal
from tenants.permissions import IsTenantAuthenticated
from wallets.pagination import TransactionCursorPagination
from wallets.selectors import get_balance, get_transaction_history, get_wallet_for_tenant
from wallets.serializers import (
    CustomerResponseSerializer,
    CustomerSerializer,
    DepositSerializer,
    TransactionSerializer,
    TransferSerializer,
    WalletBalanceSerializer,
    WithdrawSerializer,
)
from wallets.services import (
    create_customer_with_wallet,
    deposit,
    transfer,
    withdraw,
)
from wallets.utils import compute_request_hash


class TenantScopedAPIView(APIView):
    permission_classes = [IsTenantAuthenticated]

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        if isinstance(request.user, TenantPrincipal):
            request.tenant = request.user.tenant  # type: ignore[attr-defined]


class CustomerCreateView(TenantScopedAPIView):
    @extend_schema(
        request=CustomerSerializer,
        responses={201: CustomerResponseSerializer},
        summary="Create a customer and wallet",
        description="Creates a new customer under the authenticated tenant along with a default BDT wallet (balance 0).",
    )
    def post(self, request: Request) -> Response:
        serializer = CustomerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer, wallet = create_customer_with_wallet(
            tenant=request.tenant,
            username=serializer.validated_data["username"],
            email=serializer.validated_data["email"],
            currency=serializer.validated_data.get("currency", "BDT"),
        )
        data = {
            "id": customer.id,
            "username": customer.username,
            "email": customer.email,
            "wallet_id": wallet.id,
            "created_at": customer.created_at,
        }
        return Response(CustomerResponseSerializer(data).data, status=status.HTTP_201_CREATED)


class WalletDepositView(TenantScopedAPIView):
    @extend_schema(
        request=DepositSerializer,
        responses={200: TransactionSerializer},
        summary="Deposit funds into a wallet",
        description="Deposits an integer amount into the specified wallet. Requires an idempotency key (via body or Idempotency-Key header).",
    )
    def post(self, request: Request, wallet_id: UUID) -> Response:
        serializer = DepositSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        req_hash = compute_request_hash(serializer.validated_data, wallet_id=str(wallet_id))
        txn = deposit(
            tenant=request.tenant,
            wallet_id=wallet_id,
            amount=serializer.validated_data["amount"],
            idempotency_key=serializer.validated_data["idempotency_key"],
            request_hash=req_hash,
        )
        return Response(TransactionSerializer(txn).data, status=status.HTTP_200_OK)


class WalletWithdrawView(TenantScopedAPIView):
    @extend_schema(
        request=WithdrawSerializer,
        responses={200: TransactionSerializer},
        summary="Withdraw funds from a wallet",
        description="Withdraws an integer amount from the specified wallet. Returns 402 if balance is insufficient.",
    )
    def post(self, request: Request, wallet_id: UUID) -> Response:
        serializer = WithdrawSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        req_hash = compute_request_hash(serializer.validated_data, wallet_id=str(wallet_id))
        txn = withdraw(
            tenant=request.tenant,
            wallet_id=wallet_id,
            amount=serializer.validated_data["amount"],
            idempotency_key=serializer.validated_data["idempotency_key"],
            request_hash=req_hash,
        )
        return Response(TransactionSerializer(txn).data, status=status.HTTP_200_OK)


class WalletTransferView(TenantScopedAPIView):
    @extend_schema(
        request=TransferSerializer,
        responses={
            200: inline_serializer(
                name="TransferResponse",
                fields={
                    "debit": TransactionSerializer(),
                    "credit": TransactionSerializer(),
                },
            )
        },
        summary="Transfer funds between two wallets",
        description="Transfers an integer amount between two wallets owned by the same tenant. Atomically debits sender and credits receiver.",
    )
    def post(self, request: Request) -> Response:
        serializer = TransferSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        req_hash = compute_request_hash(serializer.validated_data)
        debit, credit = transfer(
            tenant=request.tenant,
            from_wallet_id=serializer.validated_data["from_wallet_id"],
            to_wallet_id=serializer.validated_data["to_wallet_id"],
            amount=serializer.validated_data["amount"],
            idempotency_key=serializer.validated_data["idempotency_key"],
            request_hash=req_hash,
        )
        return Response(
            {
                "debit": TransactionSerializer(debit).data,
                "credit": TransactionSerializer(credit).data,
            },
            status=status.HTTP_200_OK,
        )


class WalletBalanceView(TenantScopedAPIView):
    @extend_schema(
        responses={200: WalletBalanceSerializer},
        summary="Get wallet balance",
        description="Returns the current cached balance and currency for a wallet owned by the authenticated tenant.",
    )
    def get(self, request: Request, wallet_id: UUID) -> Response:
        wallet = get_wallet_for_tenant(request.tenant, wallet_id)
        balance = get_balance(wallet)
        data = {"wallet_id": wallet.id, "balance": balance, "currency": wallet.currency}
        return Response(WalletBalanceSerializer(data).data, status=status.HTTP_200_OK)


class WalletTransactionsView(TenantScopedAPIView):
    pagination_class = TransactionCursorPagination

    @extend_schema(
        responses={200: TransactionSerializer(many=True)},
        summary="Get paginated transaction history",
        description="Returns transaction history for a wallet, ordered newest-first with cursor-based pagination.",
    )
    def get(self, request: Request, wallet_id: UUID) -> Response:
        wallet = get_wallet_for_tenant(request.tenant, wallet_id)
        txns = get_transaction_history(request.tenant, wallet)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(txns, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(TransactionSerializer(page, many=True).data)
        return Response(TransactionSerializer(txns, many=True).data, status=status.HTTP_200_OK)
