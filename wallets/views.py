from __future__ import annotations

from rest_framework.request import Request
from rest_framework.views import APIView

from tenants.authentication import TenantPrincipal
from tenants.permissions import IsTenantAuthenticated


class TenantScopedAPIView(APIView):
    permission_classes = [IsTenantAuthenticated]

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        if isinstance(request.user, TenantPrincipal):
            request.tenant = request.user.tenant  # type: ignore[attr-defined]
