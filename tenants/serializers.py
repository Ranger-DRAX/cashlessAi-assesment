"""Serializers for the tenants app."""

from __future__ import annotations

from rest_framework import serializers

from tenants.models import Tenant


class TenantCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new :class:`Tenant`.

    The ``api_key`` is read-only — it is auto-generated on creation and
    returned exactly once in the response so the client can store it.
    """

    api_key = serializers.CharField(read_only=True)

    class Meta:
        model = Tenant
        fields: list[str] = ["id", "name", "api_key", "created_at"]
        read_only_fields: list[str] = ["id", "api_key", "created_at"]
