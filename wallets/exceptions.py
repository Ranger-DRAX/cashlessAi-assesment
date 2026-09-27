"""Custom exceptions for the wallets app.

Each exception maps to a specific HTTP status code via the centralised DRF
exception handler (added in a later step).  Views never catch these directly
— they bubble up to the handler which returns the appropriate response.
"""

from __future__ import annotations


class WalletNotFound(Exception):
    """Raised when a wallet lookup filtered by tenant returns no result.

    This deliberately produces a 404, not a 403, so that cross-tenant
    lookups never leak whether the object exists at all (AGENT.md rule 1).
    """


class CustomerNotFound(Exception):
    """Raised when a customer lookup filtered by tenant returns no result.

    Same isolation rationale as :class:`WalletNotFound`.
    """
