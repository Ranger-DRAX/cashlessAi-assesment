from __future__ import annotations

import logging
from typing import Tuple
from uuid import UUID

from django.db import IntegrityError, transaction

from tenants.models import Tenant
from wallets.exceptions import (
    IdempotencyKeyConflict,
    InsufficientFunds,
    InvalidAmount,
    SameWalletTransfer,
)
from wallets.models import Transaction, TransactionStatus, TransactionType, Wallet
from wallets.selectors import get_wallet_for_tenant_locked

logger = logging.getLogger(__name__)


def _check_idempotency(
    tenant: Tenant, idempotency_key: str, request_hash: str
) -> Transaction | None:
    try:
        existing = Transaction.objects.get(tenant=tenant, idempotency_key=idempotency_key)
    except Transaction.DoesNotExist:
        return None

    if existing.request_hash == request_hash:
        return existing
    raise IdempotencyKeyConflict(
        f"Idempotency key '{idempotency_key}' already used with a different payload."
    )


def _handle_integrity_race(tenant: Tenant, idempotency_key: str) -> Transaction:
    return Transaction.objects.get(tenant=tenant, idempotency_key=idempotency_key)


def deposit(
    tenant: Tenant, wallet_id: UUID, amount: int,
    idempotency_key: str, request_hash: str,
) -> Transaction:
    if amount <= 0:
        raise InvalidAmount("Deposit amount must be a positive integer.")

    existing = _check_idempotency(tenant, idempotency_key, request_hash)
    if existing is not None:
        return existing

    try:
        with transaction.atomic():
            wallet = get_wallet_for_tenant_locked(tenant, wallet_id)
            txn = Transaction.objects.create(
                tenant=tenant, wallet=wallet, type=TransactionType.DEPOSIT,
                amount=amount, idempotency_key=idempotency_key,
                request_hash=request_hash, status=TransactionStatus.COMPLETED,
            )
            wallet.cached_balance += amount
            wallet.save(update_fields=["cached_balance"])
            return txn
    except IntegrityError:
        logger.info("Deposit race on key=%s; returning existing.", idempotency_key)
        return _handle_integrity_race(tenant, idempotency_key)


def withdraw(
    tenant: Tenant, wallet_id: UUID, amount: int,
    idempotency_key: str, request_hash: str,
) -> Transaction:
    if amount <= 0:
        raise InvalidAmount("Withdrawal amount must be a positive integer.")

    existing = _check_idempotency(tenant, idempotency_key, request_hash)
    if existing is not None:
        return existing

    try:
        with transaction.atomic():
            wallet = get_wallet_for_tenant_locked(tenant, wallet_id)
            if wallet.cached_balance < amount:
                raise InsufficientFunds(
                    f"Wallet {wallet_id} has {wallet.cached_balance}, need {amount}."
                )

            txn = Transaction.objects.create(
                tenant=tenant, wallet=wallet, type=TransactionType.WITHDRAW,
                amount=amount, idempotency_key=idempotency_key,
                request_hash=request_hash, status=TransactionStatus.COMPLETED,
            )
            wallet.cached_balance -= amount
            wallet.save(update_fields=["cached_balance"])
            return txn
    except IntegrityError:
        logger.info("Withdraw race on key=%s; returning existing.", idempotency_key)
        return _handle_integrity_race(tenant, idempotency_key)


def transfer(
    tenant: Tenant, from_wallet_id: UUID, to_wallet_id: UUID,
    amount: int, idempotency_key: str, request_hash: str,
) -> Tuple[Transaction, Transaction]:
    if amount <= 0:
        raise InvalidAmount("Transfer amount must be a positive integer.")
    if from_wallet_id == to_wallet_id:
        raise SameWalletTransfer("Cannot transfer to the same wallet.")

    existing = _check_idempotency(tenant, idempotency_key, request_hash)
    if existing is not None:
        return (existing, existing.related_transaction)

    try:
        with transaction.atomic():
            first_id, second_id = sorted([from_wallet_id, to_wallet_id])
            first_wallet = get_wallet_for_tenant_locked(tenant, first_id)
            second_wallet = get_wallet_for_tenant_locked(tenant, second_id)

            sender = first_wallet if first_id == from_wallet_id else second_wallet
            receiver = second_wallet if first_id == from_wallet_id else first_wallet

            if sender.cached_balance < amount:
                raise InsufficientFunds(
                    f"Wallet {from_wallet_id} has {sender.cached_balance}, need {amount}."
                )

            debit_txn = Transaction.objects.create(
                tenant=tenant, wallet=sender, type=TransactionType.TRANSFER_DEBIT,
                amount=amount, idempotency_key=idempotency_key,
                request_hash=request_hash, status=TransactionStatus.COMPLETED,
            )
            credit_txn = Transaction.objects.create(
                tenant=tenant, wallet=receiver, type=TransactionType.TRANSFER_CREDIT,
                amount=amount, idempotency_key=f"{idempotency_key}:credit",
                request_hash=request_hash, status=TransactionStatus.COMPLETED,
            )

            debit_txn.related_transaction = credit_txn
            debit_txn.save(update_fields=["related_transaction"])
            credit_txn.related_transaction = debit_txn
            credit_txn.save(update_fields=["related_transaction"])

            sender.cached_balance -= amount
            sender.save(update_fields=["cached_balance"])
            receiver.cached_balance += amount
            receiver.save(update_fields=["cached_balance"])

            return (debit_txn, credit_txn)

    except IntegrityError:
        logger.info("Transfer race on key=%s; returning existing.", idempotency_key)
        debit = _handle_integrity_race(tenant, idempotency_key)
        return (debit, debit.related_transaction)
