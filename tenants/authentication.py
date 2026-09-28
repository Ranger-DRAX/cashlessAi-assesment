import uuid
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
            # Fallback to X-Tenant-ID, X-Api-Key, or X-Tenant-Key header per spec requirement
            x_tenant_key = (
                request.META.get("HTTP_X_TENANT_ID")
                or request.META.get("HTTP_X_API_KEY")
                or request.META.get("HTTP_X_TENANT_KEY")
            )
            if not x_tenant_key:
                return None
            key = x_tenant_key.strip()
        else:
            parts = auth_header.split()
            if len(parts) == 2:
                if parts[0].rstrip(":").lower() != self.keyword.lower():
                    raise AuthenticationFailed(
                        f"Invalid Authorization header. Expected: '{self.keyword} <api_key>'."
                    )
                key = parts[1].strip("<>\"' ")
            elif len(parts) == 1:
                if parts[0].rstrip(":").lower() == self.keyword.lower():
                    raise AuthenticationFailed(
                        f"Invalid Authorization header. Expected: '{self.keyword} <api_key>'."
                    )
                key = parts[0].strip("<>\"' ")
            else:
                raise AuthenticationFailed(
                    f"Invalid Authorization header. Expected: '{self.keyword} <api_key>'."
                )

        tenant = Tenant.objects.filter(api_key=key).first()
        if tenant is None:
            # Also check if key is a valid Tenant UUID (e.g. from X-Tenant-ID: <uuid>)
            try:
                parsed_uuid = uuid.UUID(key)
                tenant = Tenant.objects.filter(id=parsed_uuid).first()
            except (ValueError, TypeError):
                pass

        if tenant is None:
            raise AuthenticationFailed("Invalid API key or Tenant ID.")

        return (TenantPrincipal(tenant), None)

    def authenticate_header(self, request: Request) -> str:
        return self.keyword


try:
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    class TenantApiKeyScheme(OpenApiAuthenticationExtension):
        target_class = "tenants.authentication.TenantAuthentication"
        name = "ApiKeyAuth"

        def get_security_definition(self, auto_schema: object) -> dict:
            return {
                "type": "apiKey",
                "in": "header",
                "name": "Authorization",
                "description": "Enter your key in this format: Api-Key <your_api_key>",
            }
except ImportError:
    pass
