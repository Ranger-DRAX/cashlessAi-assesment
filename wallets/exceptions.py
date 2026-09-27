from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


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


CUSTOM_EXCEPTIONS_MAP: dict[type[Exception], tuple[int, str]] = {
    InsufficientFunds: (status.HTTP_402_PAYMENT_REQUIRED, "insufficient_funds"),
    WalletNotFound: (status.HTTP_404_NOT_FOUND, "wallet_not_found"),
    CustomerNotFound: (status.HTTP_404_NOT_FOUND, "customer_not_found"),
    CrossTenantTransfer: (status.HTTP_404_NOT_FOUND, "cross_tenant_transfer"),
    IdempotencyKeyConflict: (status.HTTP_409_CONFLICT, "idempotency_key_conflict"),
    InvalidAmount: (status.HTTP_400_BAD_REQUEST, "invalid_amount"),
    SameWalletTransfer: (status.HTTP_400_BAD_REQUEST, "same_wallet_transfer"),
}


def wallet_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    for exc_cls, (status_code, error_code) in CUSTOM_EXCEPTIONS_MAP.items():
        if isinstance(exc, exc_cls):
            return Response(
                {"error": error_code, "detail": str(exc)},
                status=status_code,
            )

    response = exception_handler(exc, context)
    if response is not None:
        error_code = "error"
        if isinstance(exc, APIException):
            error_code = getattr(exc, "default_code", "error")
            if hasattr(exc, "get_codes"):
                codes = exc.get_codes()
                if isinstance(codes, str):
                    error_code = codes
                elif isinstance(codes, dict):
                    error_code = "validation_error"
        detail = response.data
        if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
            detail = detail["detail"]
        response.data = {
            "error": str(error_code),
            "detail": detail,
        }
        return response

    logger.exception("Unhandled exception: %s", exc)
    return None
