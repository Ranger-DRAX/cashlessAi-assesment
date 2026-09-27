from __future__ import annotations

from typing import Any

from rest_framework import serializers

from wallets.models import Transaction


class CustomerSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    currency = serializers.CharField(max_length=3, default="BDT", required=False)


class CustomerResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
    email = serializers.EmailField()
    wallet_id = serializers.UUIDField()
    created_at = serializers.DateTimeField()


class DepositSerializer(serializers.Serializer):
    amount = serializers.IntegerField()
    idempotency_key = serializers.CharField(max_length=255, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "idempotency_key" not in attrs:
            request = self.context.get("request")
            if request:
                key = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")
                if key:
                    attrs["idempotency_key"] = key
        if not attrs.get("idempotency_key"):
            raise serializers.ValidationError({"idempotency_key": ["This field is required."]})
        return attrs


class WithdrawSerializer(serializers.Serializer):
    amount = serializers.IntegerField()
    idempotency_key = serializers.CharField(max_length=255, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "idempotency_key" not in attrs:
            request = self.context.get("request")
            if request:
                key = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")
                if key:
                    attrs["idempotency_key"] = key
        if not attrs.get("idempotency_key"):
            raise serializers.ValidationError({"idempotency_key": ["This field is required."]})
        return attrs


class TransferSerializer(serializers.Serializer):
    from_wallet_id = serializers.UUIDField()
    to_wallet_id = serializers.UUIDField()
    amount = serializers.IntegerField()
    idempotency_key = serializers.CharField(max_length=255, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "idempotency_key" not in attrs:
            request = self.context.get("request")
            if request:
                key = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")
                if key:
                    attrs["idempotency_key"] = key
        if not attrs.get("idempotency_key"):
            raise serializers.ValidationError({"idempotency_key": ["This field is required."]})
        return attrs


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
