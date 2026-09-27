"""Custom permissions for tenant-scoped access control."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from tenants.authentication import TenantPrincipal

if TYPE_CHECKING:
    from rest_framework.views import APIView


class IsTenantAuthenticated(BasePermission):
    """Allow access only to requests that resolved to a valid tenant.

    Works in tandem with :class:`~tenants.authentication.TenantAuthentication`
    which stores a :class:`~tenants.authentication.TenantPrincipal` on
    ``request.user``.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Check whether the request has a valid tenant principal.

        Args:
            request: The incoming DRF request.
            view: The view being accessed.

        Returns:
            ``True`` if ``request.user`` is a :class:`TenantPrincipal`,
            ``False`` otherwise.
        """
        return isinstance(request.user, TenantPrincipal)
