# Step 3 — Wire up tenant authentication

Read `AGENT.md` first, especially rule 1 (tenant isolation is absolute).

## Objective

Make every future view automatically get a validated `request.tenant`, with
zero per-view boilerplate, and make it impossible to write a view that
forgets to check it.

## Requirements

- `tenants/authentication.py`: a DRF `BaseAuthentication` subclass,
  `TenantAuthentication`, that:
  - Reads an API key from either the `X-Tenant-ID` header or an
    `Authorization: Api-Key <key>` header — pick one convention and
    document it in a docstring, but support looking it up by `api_key`.
  - Looks up the matching `Tenant`. If none is found, raise
    `rest_framework.exceptions.AuthenticationFailed` with a clear message
    — do not let this fall through to a generic 500.
  - On success, returns `(tenant, None)` per DRF's authentication contract,
    and the view layer should expose it as `request.tenant` (DRF puts the
    first tuple element on `request.user` by convention, but that's wrong
    here — you have two clean options: wrap the tenant in a lightweight
    object that also satisfies whatever `IsAuthenticated`-style permission
    you use, or add a small piece of middleware/mixin that copies it to
    `request.tenant` explicitly. Pick one and document why in a code
    comment.)
- Register `TenantAuthentication` as a default authentication class in
  `settings.py`, and add a base `TenantScopedAPIView` (or a mixin) in
  `wallets/views.py` — or a shared location — that all wallet/customer
  views will inherit from in later steps, so tenant-resolution failure is
  handled once, not per view.
- Write a temporary throwaway view (or a test) to prove this works end to
  end — you can delete the throwaway view once step 4+ views exist, but
  don't skip verifying it.
- Do not implement tenant *creation* here if it doesn't already exist from
  a prior step — if `POST /api/tenants/` isn't built yet, add a minimal
  version now (serializer + view + url) since every other step's testing
  depends on being able to create a tenant and read back its `api_key`.

## Acceptance criteria

- [ ] A request with a valid tenant key attaches a real `Tenant` instance,
      accessible as `request.tenant`, to the view.
- [ ] A request with a missing or invalid key returns `401`, not `500` or
      an unhandled exception.
- [ ] `POST /api/tenants/` exists, creates a `Tenant`, and returns its
      `api_key` in the response body exactly once (this is the only time a
      client should need to see it echoed back).
- [ ] There is at least one automated test proving both the success and
      failure path of `TenantAuthentication`.

Commit as `feat: add tenant resolution via API key authentication`.
