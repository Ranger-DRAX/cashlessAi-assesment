from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from tenants.authentication import TenantPrincipal

if TYPE_CHECKING:
    from rest_framework.views import APIView


class IsTenantAuthenticated(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.user, TenantPrincipal)
