from __future__ import annotations

from typing import Optional, Tuple

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from tenants.models import Tenant


class TenantPrincipal:
    is_authenticated: bool = True

    def __init__(self, tenant: Tenant) -> None:
        self.tenant = tenant

    def __str__(self) -> str:
        return f"TenantPrincipal({self.tenant.name})"


class TenantAuthentication(BaseAuthentication):
    keyword: str = "Api-Key"

    def authenticate(self, request: Request) -> Optional[Tuple[TenantPrincipal, None]]:
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is None:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            raise AuthenticationFailed(
                f"Invalid Authorization header. Expected: '{self.keyword} <api_key>'."
            )

        try:
            tenant = Tenant.objects.get(api_key=parts[1])
        except Tenant.DoesNotExist:
            raise AuthenticationFailed("Invalid API key.")

        return (TenantPrincipal(tenant), None)

    def authenticate_header(self, request: Request) -> str:
        return self.keyword
