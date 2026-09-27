"""Tenant model — the top-level isolation boundary for the multi-tenant API."""

import secrets
import uuid

from django.db import models


class Tenant(models.Model):
    """A tenant represents an isolated organisation with its own customers,
    wallets, and transaction ledger.

    Attributes:
        id: UUID primary key.
        name: Human-readable tenant name.
        api_key: Unique, indexed key used to authenticate requests on behalf
            of this tenant.  Auto-generated with ``secrets.token_urlsafe`` when
            not explicitly provided.
        created_at: Timestamp of creation.
    """

    id: models.UUIDField = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    name: models.CharField = models.CharField(max_length=255)
    api_key: models.CharField = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        default=secrets.token_urlsafe,
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Tenant({self.name})"
