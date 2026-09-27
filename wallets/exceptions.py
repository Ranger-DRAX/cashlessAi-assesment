from __future__ import annotations


class WalletNotFound(Exception):
    pass


class CustomerNotFound(Exception):
    pass


class InsufficientFunds(Exception):
    pass


class IdempotencyKeyConflict(Exception):
    pass


class InvalidAmount(Exception):
    pass


class CrossTenantTransfer(Exception):
    pass


class SameWalletTransfer(Exception):
    pass
