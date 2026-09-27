"""Base views and mixins for tenant-scoped endpoints.

All wallet/customer views inherit from :class:`TenantScopedAPIView` so that
``request.tenant`` is always available and tenant resolution failures are
handled in exactly one place.
"""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.views import APIView

from tenants.authentication import TenantPrincipal
from tenants.models import Tenant
from tenants.permissions import IsTenantAuthenticated


class TenantScopedAPIView(APIView):
    """Base view that guarantees ``request.tenant`` is set.

    Copies ``request.user.tenant`` (set by
    :class:`~tenants.authentication.TenantAuthentication`) to
    ``request.tenant`` during ``initial()`` so downstream handler methods
    can access the tenant without knowing about the ``TenantPrincipal``
    wrapper.

    All wallet and customer views should inherit from this class.
    """

    permission_classes: list = [IsTenantAuthenticated]

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        """Run DRF's standard initialisation, then set ``request.tenant``.

        Args:
            request: The incoming DRF request.
            *args: Positional arguments forwarded to ``super().initial()``.
            **kwargs: Keyword arguments forwarded to ``super().initial()``.
        """
        super().initial(request, *args, **kwargs)

        # At this point authentication + permission checks have passed,
        # so request.user is guaranteed to be a TenantPrincipal.
        if isinstance(request.user, TenantPrincipal):
            request.tenant = request.user.tenant  # type: ignore[attr-defined]
