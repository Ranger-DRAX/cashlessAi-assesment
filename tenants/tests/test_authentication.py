from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from tenants.models import Tenant


class TenantAuthenticationTests(TestCase):
    def setUp(self) -> None:
        self.client: APIClient = APIClient()
        self.tenant: Tenant = Tenant.objects.create(name="Test Corp")

    def test_valid_api_key_returns_200_and_tenant_info(self) -> None:
        response = self.client.get(
            "/api/tenants/ping/",
            HTTP_AUTHORIZATION=f"Api-Key {self.tenant.api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "pong")
        self.assertEqual(response.data["tenant_id"], str(self.tenant.id))
        self.assertEqual(response.data["tenant_name"], self.tenant.name)

    def test_missing_auth_header_returns_401(self) -> None:
        response = self.client.get("/api/tenants/ping/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_api_key_returns_401(self) -> None:
        response = self.client.get(
            "/api/tenants/ping/",
            HTTP_AUTHORIZATION="Api-Key totally-bogus-key",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_malformed_auth_header_returns_401(self) -> None:
        response = self.client.get(
            "/api/tenants/ping/",
            HTTP_AUTHORIZATION="Bearer some-token",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empty_api_key_returns_401(self) -> None:
        response = self.client.get(
            "/api/tenants/ping/",
            HTTP_AUTHORIZATION="Api-Key",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TenantCreateViewTests(TestCase):
    def setUp(self) -> None:
        self.client: APIClient = APIClient()

    def test_create_tenant_returns_201_with_api_key(self) -> None:
        response = self.client.post(
            "/api/tenants/",
            data={"name": "Acme Inc"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("api_key", response.data)
        self.assertIn("id", response.data)
        self.assertEqual(response.data["name"], "Acme Inc")
        self.assertTrue(
            Tenant.objects.filter(api_key=response.data["api_key"]).exists()
        )

    def test_create_tenant_without_name_returns_400(self) -> None:
        response = self.client.post(
            "/api/tenants/",
            data={},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
