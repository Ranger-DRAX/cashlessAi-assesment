from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView


def api_not_found(request: object, *args: object, **kwargs: object) -> JsonResponse:
    return JsonResponse(
        {"error": "not_found", "detail": "The requested API endpoint was not found."},
        status=404,
    )


urlpatterns: list = [
    path("admin/", admin.site.urls),
    path("api/tenants/", include("tenants.urls")),
    path("api/", include("wallets.urls")),
    # OpenAPI schema + interactive docs (no auth required)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    re_path(r"^api/.*$", api_not_found),
]
