from __future__ import annotations

from typing import Any

from rest_framework import serializers

from wallets.models import Transaction

# PostgreSQL bigint max — amounts beyond this cause a DataError at the DB layer.
_AMOUNT_MAX = 9_223_372_036_854_775_807

# Idempotency key max length must match the model column (varchar 255).
_IDEM_KEY_MAX_LENGTH = 255


class StrictIntegerField(serializers.IntegerField):
    """
    Rejects float values and string representations of numbers.
    DRF's IntegerField coerces "100" and 100.0 to 100, which is surprising
    for a JSON-only API where the client should always send a bare integer.
    """

    def to_internal_value(self, data: Any) -> int:
        if isinstance(data, (float, bool)):
            self.fail("invalid")
        if isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class _IdempotencyKeyMixin:
    """
    Resolves the idempotency key from either the request body or the
    Idempotency-Key HTTP header, validates it (max 255 chars, stripped),
    and raises a ValidationError if it is absent from both sources.

    Must be mixed into a Serializer subclass that passes `request` via context.
    """

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        key: str | None = attrs.get("idempotency_key")

        if not key:
            request = self.context.get("request")  # type: ignore[attr-defined]
            if request:
                raw = request.headers.get("Idempotency-Key", "").strip()
                if raw:
                    if len(raw) > _IDEM_KEY_MAX_LENGTH:
                        raise serializers.ValidationError(
                            {"idempotency_key": [
                                f"Ensure this value has at most {_IDEM_KEY_MAX_LENGTH} characters."
                            ]}
                        )
                    key = raw

        if not key:
            raise serializers.ValidationError(
                {"idempotency_key": ["This field is required."]}
            )

        attrs["idempotency_key"] = key
        return attrs


class CustomerSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    # Currency is fixed to BDT for this version. The field is not exposed so
    # callers cannot supply an arbitrary 3-char string.


class CustomerResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
    email = serializers.EmailField()
    wallet_id = serializers.UUIDField()
    created_at = serializers.DateTimeField()


class DepositSerializer(_IdempotencyKeyMixin, serializers.Serializer):
    amount = StrictIntegerField(max_value=_AMOUNT_MAX)
    idempotency_key = serializers.CharField(
        max_length=_IDEM_KEY_MAX_LENGTH, required=False, trim_whitespace=True
    )


class WithdrawSerializer(_IdempotencyKeyMixin, serializers.Serializer):
    amount = StrictIntegerField(max_value=_AMOUNT_MAX)
    idempotency_key = serializers.CharField(
        max_length=_IDEM_KEY_MAX_LENGTH, required=False, trim_whitespace=True
    )


class TransferSerializer(_IdempotencyKeyMixin, serializers.Serializer):
    from_wallet_id = serializers.UUIDField()
    to_wallet_id = serializers.UUIDField()
    amount = StrictIntegerField(max_value=_AMOUNT_MAX)
    idempotency_key = serializers.CharField(
        max_length=_IDEM_KEY_MAX_LENGTH, required=False, trim_whitespace=True
    )


class WalletBalanceSerializer(serializers.Serializer):
    wallet_id = serializers.UUIDField()
    balance = serializers.IntegerField()
    currency = serializers.CharField(max_length=3)


class TransactionSerializer(serializers.ModelSerializer):
    wallet_id = serializers.UUIDField(read_only=True)
    related_transaction_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "wallet_id",
            "type",
            "amount",
            "related_transaction_id",
            "idempotency_key",
            "status",
            "created_at",
        ]
        read_only_fields = fields
