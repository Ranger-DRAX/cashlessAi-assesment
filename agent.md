# AGENT.md — Multi-tenant wallet API (Django + DRF)

This file is persistent project context. Read it in full before writing any
code, and re-read it if you're resuming this project in a new session. The
files in `steps/` (`01-scaffold-project.md` through `09-dockerize.md`) are
separate prompts, meant to be given to you one at a time, in order. Do not
start a later step before the current one's acceptance criteria all pass.
If a later step's instructions ever seem to conflict with a rule in this
file, stop and flag the conflict instead of silently picking one.

Note the ordering: Docker is step 9, deliberately last. Steps 1–8 are
developed and verified against a locally running Postgres — no
`docker-compose.yml` or `Dockerfile` exists until step 9 wraps the
already-working application. Don't add either earlier, even if it seems
convenient to do both at once in step 1.

## What this project is

A REST API, built with Django + Django REST Framework, backed by PostgreSQL,
that supports:

- Creating a tenant
- Creating a customer (and their wallet) under a tenant
- Depositing funds into a wallet
- Withdrawing funds, rejecting the request if the balance is insufficient
- Transferring funds between two wallets that belong to the same tenant
- Reading a wallet's balance and a paginated transaction history

## Non-negotiable rules

These apply across every step, not just the step that first introduces them.

1. **Tenant isolation is absolute.** Every request resolves to exactly one
   tenant, via an `X-Tenant-ID` header or an API key. Every query for a
   `Customer`, `Wallet`, or `Transaction` must be filtered by that tenant.
   A tenant requesting another tenant's object gets a `404`, never a `403`
   — a `403` leaks that the object exists at all.
2. **The ledger is the source of truth.** Every balance change is an
   immutable `Transaction` row. Never write code that changes a balance
   field without writing the matching ledger row in the same atomic block.
3. **Money is never a float.** Use `DecimalField` or an integer minor-units
   field (paisa/cents). No `FloatField` anywhere near money, ever.
4. **Deposit, withdraw, and transfer are idempotent, scoped per tenant.**
   Each accepts an `Idempotency-Key`. A repeated key with the same payload
   returns the original result without reprocessing. A repeated key with a
   *different* payload is a `409 Conflict`.
5. **Transfers are atomic and same-tenant only.** Both legs of a transfer
   succeed or neither does. A transfer across two different tenants is
   rejected before either wallet is touched.
6. **Concurrency-safe.** Any code path that reads a wallet's balance before
   writing to it locks that row with `select_for_update()` inside a
   `transaction.atomic()` block. Never "read balance, then decide, then
   write" without holding the lock across all three.

## Code quality bar

- Type hints on every function signature. Google-style docstrings on every
  public function and class.
- Format with Black, order imports with isort, before considering any step
  finished.
- Views are thin: parse input with a serializer, call one function from
  `services.py`, serialize the result. No business logic in `views.py`.
- All reads go through `selectors.py`; all writes go through `services.py`.
  Nothing in `views.py` touches the ORM directly.
- Custom exceptions live in `exceptions.py`, mapped centrally to HTTP status
  codes by one DRF exception handler — not ad hoc `try/except` blocks
  scattered per view.
- No bare `except Exception`. Catch specific exceptions; `logger.exception()`
  anything unexpected before re-raising.
- No magic numbers or bare strings for fixed choices — use `TextChoices` or
  `enum.Enum` for transaction types and statuses.
- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`), one
  logical change per commit.

## Repository layout

| File/module | What belongs there |
|---|---|
| `tenants/models.py` | `Tenant` model, API key field |
| `tenants/authentication.py` | Resolves the tenant from the request, attaches `request.tenant` |
| `tenants/serializers.py`, `views.py`, `urls.py` | Tenant creation endpoint |
| `wallets/models.py` | `Customer`, `Wallet`, `Transaction` (the ledger) |
| `wallets/serializers.py` | Input/output validation |
| `wallets/services.py` | `deposit`, `withdraw`, `transfer` — all business logic |
| `wallets/selectors.py` | Tenant-scoped balance and history queries |
| `wallets/exceptions.py` | Custom exceptions + the DRF exception handler |
| `wallets/views.py` | Thin HTTP handling only |
| `wallets/urls.py` | Endpoint routing |
| `wallets/tests/`, `tenants/tests/` | Correctness and isolation tests |
| `Dockerfile`, `docker-compose.yml` | Added in step 9, after the app works locally — not present before then |

## Data model summary

- **Tenant**: `id`, `name`, `api_key` (unique), `created_at`
- **Customer**: `id`, `tenant` (FK), `username`, `email`, `created_at`
- **Wallet**: `id`, `tenant` (FK), `customer` (FK), `currency`,
  `cached_balance` (integer minor units), `created_at`
- **Transaction**: `id`, `tenant` (FK), `wallet` (FK), `type`
  (`deposit`/`withdraw`/`transfer_debit`/`transfer_credit`), `amount`,
  `related_transaction` (self FK, nullable, links the two legs of a
  transfer), `idempotency_key`, `status`, `created_at`.
  Unique together: `(tenant, idempotency_key)`.

`cached_balance` is a convenience for cheap balance reads — it is written
only inside the same atomic block as the ledger row that justifies it. If it
and the ledger ever disagree, the ledger wins.

## API summary

| Endpoint | Method | Purpose | Idempotent? |
|---|---|---|---|
| `/api/tenants/` | POST | Create a tenant | No |
| `/api/customers/` | POST | Create a customer + wallet under the tenant | No |
| `/api/wallets/{id}/deposit/` | POST | Add funds | Yes |
| `/api/wallets/{id}/withdraw/` | POST | Remove funds, 402 if insufficient | Yes |
| `/api/wallets/transfer/` | POST | Move funds, same tenant only | Yes |
| `/api/wallets/{id}/balance/` | GET | Current balance | N/A |
| `/api/wallets/{id}/transactions/` | GET | Paginated ledger history | N/A |

## How to work through the steps

Work one `steps/0N-*.md` file at a time. After finishing a step: run the
test suite if one exists yet, check off every item in that step's
acceptance criteria explicitly in your response, and stop — wait for the
next step file rather than continuing on your own initiative.