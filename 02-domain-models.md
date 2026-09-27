# Step 2 — Build the models

Read `AGENT.md` in the repo root first, especially "Data model summary" and
rule 3 (money is never a float). This step implements that schema exactly.

## Objective

Create `Tenant`, `Customer`, `Wallet`, and `Transaction` as Django models,
with every constraint the ledger design depends on already enforced at the
database level — not left to application code to remember.

## Requirements

- `tenants/models.py`: `Tenant` with `id` (UUID primary key), `name`,
  `api_key` (unique, indexed, generated with `secrets.token_urlsafe` on
  creation if not provided), `created_at`.
- `wallets/models.py`:
  - `Customer`: `id` (UUID), `tenant` (FK to `Tenant`, `on_delete=PROTECT`),
    `username`, `email`, `created_at`. Unique together: `(tenant, username)`.
  - `Wallet`: `id` (UUID), `tenant` (FK), `customer` (FK,
    `on_delete=PROTECT`), `currency` (default `"BDT"` or similar), `cached_balance`
    (integer minor units, default 0, `db_index=True` not required), `created_at`.
  - `Transaction`: `id` (UUID), `tenant` (FK), `wallet` (FK,
    `related_name="transactions"`), `type` (`TextChoices`: `DEPOSIT`,
    `WITHDRAW`, `TRANSFER_DEBIT`, `TRANSFER_CREDIT`), `amount` (integer
    minor units, always positive — direction is implied by `type`, never a
    signed amount), `related_transaction` (self FK, nullable, blank,
    `on_delete=PROTECT`, links the two legs of a transfer),
    `idempotency_key` (string, indexed), `status` (`TextChoices`:
    `COMPLETED`, `FAILED`), `created_at`.
  - On `Transaction`, add `unique_together = ("tenant", "idempotency_key")`
    at the database level via `UniqueConstraint` — this is what makes
    concurrent duplicate requests safe, not a Python-level check.
  - Add a `CheckConstraint` on `Transaction.amount` enforcing `amount > 0`.
  - Add sensible `__str__` methods on all four models for admin/debugging
    readability.
- Do not add a mutable `balance` field that application code increments —
  `cached_balance` is the only balance-like field, and later steps will
  only ever write it inside the same atomic block as a `Transaction` row.
- Register all four models in `admin.py` for each app (list_display with
  the key fields) — this is for your own debugging convenience during
  development, not a spec requirement.
- Generate and apply migrations.

## Acceptance criteria

- [ ] `python manage.py makemigrations` produces migrations with no
      warnings; `migrate` applies cleanly on a fresh database.
- [ ] The `(tenant, idempotency_key)` uniqueness is a real
      `UniqueConstraint` in the migration, not just a Python-level check —
      confirm by inspecting the generated migration file.
- [ ] `Transaction.amount` has a database-level check that it's positive.
- [ ] No field anywhere in these models is a `FloatField`.
- [ ] All four models are visible and usable in `/admin/`.

Commit as `feat: add Tenant, Customer, Wallet, and Transaction models`.
