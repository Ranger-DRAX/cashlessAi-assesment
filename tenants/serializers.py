from __future__ import annotations

from rest_framework import serializers

from tenants.models import Tenant


class TenantCreateSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(read_only=True)

    class Meta:
        model = Tenant
        fields: list[str] = ["id", "name", "api_key", "created_at"]
        read_only_fields: list[str] = ["id", "api_key", "created_at"]
