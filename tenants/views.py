from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema

from tenants.models import Tenant
from tenants.permissions import IsTenantAuthenticated
from tenants.serializers import TenantCreateSerializer


class TenantCreateView(APIView):
    authentication_classes: list = []
    permission_classes: list = [AllowAny]

    @extend_schema(
        auth=[],
        request=TenantCreateSerializer,
        responses={201: TenantCreateSerializer},
        summary="Create a new tenant (Public)",
        description="Registers a new tenant organisation and returns an API key. Save this API key to authorize future requests.",
    )
    def post(self, request: Request) -> Response:
        serializer = TenantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TenantPingView(APIView):
    permission_classes: list = [IsTenantAuthenticated]

    @extend_schema(
        summary="Test tenant authentication",
        description="Returns tenant information to verify that your Api-Key is valid.",
    )
    def get(self, request: Request) -> Response:
        tenant: Tenant = request.user.tenant
        return Response(
            {
                "message": "pong",
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
            },
            status=status.HTTP_200_OK,
        )
