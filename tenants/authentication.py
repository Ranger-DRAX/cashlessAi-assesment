"""Tenant authentication backend for Django REST Framework.

Convention chosen: ``Authorization: Api-Key <key>`` header.

This is preferred over ``X-Tenant-ID`` because:
- It follows HTTP semantics (``Authorization`` is the standard header for
  credentials).
- It avoids leaking tenant structure in a custom header that proxies/CDNs
  might strip.
- DRF's ``request.auth`` remains ``None`` (we aren't using token auth), and
  the tenant is surfaced as ``request.tenant`` via a lightweight wrapper
  stored on ``request.user``.

Design decision — ``request.tenant`` exposure:
    DRF places the first element of the ``(user, auth)`` tuple on
    ``request.user``.  Storing a ``Tenant`` there directly would break any
    code that expects ``request.user`` to be a Django ``User`` or
    ``AnonymousUser``.  Instead we wrap the ``Tenant`` in a tiny
    ``TenantPrincipal`` object that:
    1. Carries ``tenant`` as an attribute,
    2. Reports ``is_authenticated = True`` so ``IsAuthenticated``-style
       permissions pass without customisation,
    3. Is *not* a Django ``User`` — making accidental user-level queries
       fail fast rather than silently returning wrong data.

    A ``TenantScopedAPIView`` base class (in ``wallets/views.py``) copies
    ``request.user.tenant`` to ``request.tenant`` in ``initial()`` for
    ergonomic access in all downstream views.
"""

from __future__ import annotations

from typing import Optional, Tuple

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from tenants.models import Tenant


class TenantPrincipal:
    """Lightweight wrapper that DRF stores on ``request.user``.

    Attributes:
        tenant: The resolved :class:`~tenants.models.Tenant` instance.
        is_authenticated: Always ``True`` so DRF's ``IsAuthenticated``
            permission passes.
    """

    is_authenticated: bool = True

    def __init__(self, tenant: Tenant) -> None:
        self.tenant: Tenant = tenant

    def __str__(self) -> str:
        return f"TenantPrincipal({self.tenant.name})"


class TenantAuthentication(BaseAuthentication):
    """Resolve a tenant from the ``Authorization: Api-Key <key>`` header.

    Returns ``(TenantPrincipal, None)`` on success so that:
    - ``request.user.tenant`` gives the :class:`~tenants.models.Tenant`.
    - ``request.user.is_authenticated`` is ``True``.

    Raises:
        AuthenticationFailed: If the header is missing, malformed, or the
            key does not match any tenant.
    """

    keyword: str = "Api-Key"

    def authenticate(
        self, request: Request
    ) -> Optional[Tuple[TenantPrincipal, None]]:
        """Extract and validate the API key from the request.

        Args:
            request: The incoming DRF request.

        Returns:
            A ``(TenantPrincipal, None)`` tuple when a valid key is found,
            or ``None`` if the ``Authorization`` header is absent (allowing
            DRF to fall through to the next authenticator or deny access).
        """
        auth_header: Optional[str] = request.META.get("HTTP_AUTHORIZATION")

        if auth_header is None:
            return None  # No credentials provided — let DRF handle it.

        parts: list[str] = auth_header.split()

        if len(parts) != 2 or parts[0] != self.keyword:
            raise AuthenticationFailed(
                "Invalid Authorization header. "
                f"Expected format: '{self.keyword} <api_key>'."
            )

        api_key: str = parts[1]

        try:
            tenant: Tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise AuthenticationFailed(
                "Invalid API key. No tenant found for the provided key."
            )

        return (TenantPrincipal(tenant), None)

    def authenticate_header(self, request: Request) -> str:
        """Return the value for the ``WWW-Authenticate`` response header.

        Args:
            request: The incoming DRF request.

        Returns:
            The authentication scheme name.
        """
        return self.keyword
