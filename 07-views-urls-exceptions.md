# Step 7 — Add views, urls, and the exception handler

Read `AGENT.md` first, especially "views are thin" and the exceptions rule
in the code quality bar.

## Objective

Expose everything built in steps 2–6 over HTTP, with every error type
mapping to one consistent JSON shape and the right status code — no view
inventing its own error format.

## Requirements

`wallets/exceptions.py`: add a DRF custom exception handler,
`wallet_exception_handler`, registered in `settings.py` under
`REST_FRAMEWORK["EXCEPTION_HANDLER"]`. It must map:

- `InsufficientFunds` → `402 Payment Required`
- `WalletNotFound`, `CustomerNotFound` → `404 Not Found`
- `IdempotencyKeyConflict` → `409 Conflict`
- `InvalidAmount` and any DRF `ValidationError` → `400 Bad Request`
- Anything unhandled → fall through to DRF's default handler (which
  produces a `500`), after `logger.exception()`-ing it first.

Every error response body follows one shape, e.g.
`{"error": "<snake_case_code>", "detail": "<human message>"}` — pick the
exact shape and use it consistently across every exception above.

`wallets/serializers.py`:

- `DepositSerializer`, `WithdrawSerializer`: `amount` (positive integer),
  `idempotency_key` (required string).
- `TransferSerializer`: `from_wallet_id`, `to_wallet_id`, `amount`,
  `idempotency_key`.
- `TransactionSerializer`: read-only, for the history endpoint.
- `WalletBalanceSerializer`: `wallet_id`, `balance`, `currency`.
- `CustomerSerializer`: for `POST /api/customers/`, creating a `Customer`
  and its `Wallet` together in one call.

`wallets/views.py` (all inheriting the tenant-scoped base from step 3):

- `POST /api/customers/` — create customer + wallet.
- `POST /api/wallets/{id}/deposit/`
- `POST /api/wallets/{id}/withdraw/`
- `POST /api/wallets/transfer/`
- `GET /api/wallets/{id}/balance/`
- `GET /api/wallets/{id}/transactions/` — paginated, using the pagination
  class configured in step 1.

Every view: validate with a serializer, call exactly one function from
`services.py` or `selectors.py`, serialize and return. Compute
`request_hash` (e.g. a hash of the validated serializer data) in the view
or a small shared helper — not duplicated inline in three places.

`wallets/urls.py` and `tenants/urls.py`: wire all of the above plus
`POST /api/tenants/` from step 3, included from the project's root
`config/urls.py`.

## Acceptance criteria

- [ ] Every endpoint in `AGENT.md`'s API summary table exists and responds.
- [ ] Triggering each custom exception (insufficient funds, wrong tenant,
      duplicate idempotency key with different payload, invalid amount)
      returns the correct status code and the same JSON error shape for
      all of them — proven with a test per exception type.
- [ ] The transaction history endpoint is paginated and returns newest-first.
- [ ] No `views.py` function is longer than roughly 15 lines — if one is,
      that's a sign logic leaked out of `services.py`.

Commit as `feat: expose wallet API endpoints with unified error handling`.
