# Step 4 — Write tenant-scoped selectors

Read `AGENT.md` first, especially rule 1 and the "reads go through
selectors.py" rule in the code quality bar.

## Objective

Build the one place in the codebase that's allowed to read `Wallet` and
`Transaction` rows, so every later view and service reuses it instead of
writing its own queryset — and every read is provably tenant-scoped.

## Requirements

`wallets/selectors.py`, with every function taking `tenant` as its first,
required argument:

- `get_wallet_for_tenant(tenant: Tenant, wallet_id: UUID) -> Wallet` — looks
  up the wallet filtered by both `id` and `tenant`. Raise a custom
  `WalletNotFound` exception (define it in `wallets/exceptions.py`, created
  in this step if it doesn't exist yet) if no match — this is what turns a
  cross-tenant lookup into a clean 404 instead of leaking a 403 or raising
  `Wallet.DoesNotExist` uncaught.
- `get_balance(wallet: Wallet) -> int` — returns `cached_balance`. Add a
  short docstring noting this trusts the cache and is intentionally cheap;
  it does not resum the ledger.
- `get_transaction_history(tenant: Tenant, wallet: Wallet) -> QuerySet` —
  returns `Transaction.objects.filter(tenant=tenant, wallet=wallet)`
  ordered newest-first, ready to be handed to a DRF paginator. Do not
  paginate inside the selector — that's the view's job.
- `get_customer_for_tenant(tenant: Tenant, customer_id: UUID) -> Customer`
  — same pattern as the wallet lookup, for use by the customer-creation /
  lookup endpoints.

Every one of these functions must be literally incapable of returning
another tenant's data — the `tenant` filter is not optional and not a
default argument.

## Acceptance criteria

- [ ] Every function in `selectors.py` requires `tenant` as an argument;
      none accepts just an `id` alone.
- [ ] Calling `get_wallet_for_tenant` with a wallet ID that belongs to a
      different tenant raises `WalletNotFound`, proven by a test.
- [ ] `wallets/views.py` (even if mostly still stubs at this point) does
      not contain a single bare `Wallet.objects.get(...)` or
      `.filter(...)` call — everything goes through this file.

Commit as `feat: add tenant-scoped selectors for wallets and transactions`.
