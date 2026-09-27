# Step 6 — Implement transfer

Read `AGENT.md` first, especially rules 1, 2, 5, and 6. Read step 5's file
too — transfer reuses its idempotency pattern exactly; this file only
covers what's different.

## Objective

Move funds between two wallets in the same tenant, as a single atomic unit,
safe against cross-tenant transfers and against deadlocking with a
simultaneous transfer running in the opposite direction.

## Requirements

`wallets/exceptions.py`: add `CrossTenantTransfer`.

`wallets/services.py`:

- `transfer(tenant, from_wallet_id, to_wallet_id, amount, idempotency_key, request_hash) -> tuple[Transaction, Transaction]`

Order of operations:

1. Validate `amount > 0` and `from_wallet_id != to_wallet_id` before
   touching the database.
2. Run the same idempotency check as `deposit`/`withdraw` from step 5
   (existing key + matching hash → return early; existing key + different
   hash → `IdempotencyKeyConflict`).
3. Fetch both wallets via `get_wallet_for_tenant` for the *same* `tenant`
   argument. If either lookup fails (wrong tenant or doesn't exist), that
   failure alone already enforces the same-tenant rule — you do not need a
   separate tenant-equality check as long as both lookups are scoped to the
   one `tenant` passed in. Document this in a comment so it's obvious to a
   reviewer why there's no explicit `if wallet_a.tenant != wallet_b.tenant`
   check.
4. Inside one `transaction.atomic()` block, lock both wallets with
   `select_for_update()` **in a consistent order** — e.g. sort the two
   wallet IDs and lock the lower one first. This is required: without a
   fixed order, a transfer A→B running concurrently with a transfer B→A can
   deadlock, each holding the lock the other needs.
5. Re-check the sender's `cached_balance >= amount` after both locks are
   held. Raise `InsufficientFunds` if it fails.
6. Create two linked `Transaction` rows — `TRANSFER_DEBIT` on the sender's
   wallet and `TRANSFER_CREDIT` on the receiver's — each with
   `related_transaction` pointing at the other. Update both wallets'
   `cached_balance` in the same block.
7. Apply the same `IntegrityError`-on-duplicate-insert handling from step 5
   for the case where two identical transfer retries race each other.

## Acceptance criteria

- [ ] A test asserts a transfer between two wallets in different tenants
      fails (via the normal wallet-not-found path) and writes nothing.
- [ ] A test asserts transferring more than the sender's balance raises
      `InsufficientFunds` and leaves both wallets and the transaction table
      unchanged.
- [ ] A test asserts a successful transfer creates exactly two `Transaction`
      rows, linked via `related_transaction`, with the debit and credit
      amounts equal.
- [ ] A concurrency test runs transfer A→B and transfer B→A at the same
      time and confirms neither deadlocks and both complete (or one
      legitimately fails on insufficient funds — but never a deadlock or
      partial write).
- [ ] Repeating the exact same transfer request with its original
      idempotency key does not create a third or fourth transaction row.

Commit as `feat: implement atomic, same-tenant wallet transfers`.
