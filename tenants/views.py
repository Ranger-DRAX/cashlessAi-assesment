"""Views for the tenants app."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.models import Tenant
from tenants.permissions import IsTenantAuthenticated
from tenants.serializers import TenantCreateSerializer


class TenantCreateView(APIView):
    """Create a new tenant.

    ``POST /api/tenants/``

    This endpoint is open (no API key required) because the tenant doesn't
    exist yet — the ``api_key`` is returned in the response body exactly once.
    """

    authentication_classes: list = []  # No auth needed to *create* a tenant.
    permission_classes: list = [AllowAny]

    def post(self, request: Request) -> Response:
        """Handle tenant creation.

        Args:
            request: The incoming DRF request containing ``{"name": "..."}``

        Returns:
            ``201 Created`` with the tenant details including ``api_key``.
        """
        serializer = TenantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TenantPingView(APIView):
    """Temporary throwaway view to verify tenant authentication works.

    ``GET /api/tenants/ping/``

    Returns the authenticated tenant's name and ID.  Delete this view once
    real tenant-scoped views exist in later steps.
    """

    permission_classes: list = [IsTenantAuthenticated]

    def get(self, request: Request) -> Response:
        """Return the authenticated tenant's details.

        Args:
            request: The incoming DRF request with a valid API key.

        Returns:
            ``200 OK`` with tenant name and ID.
        """
        tenant: Tenant = request.user.tenant
        return Response(
            {
                "message": "pong",
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
            },
            status=status.HTTP_200_OK,
        )
