# Step 5 — Implement deposit and withdraw

Read `AGENT.md` first, especially rules 2, 4, and 6 (ledger as source of
truth, idempotency, concurrency-safety). This is the first step where a
subtle bug can silently corrupt money — go slowly and re-read the
requirements before writing each function.

## Objective

Implement `deposit` and `withdraw` in the service layer, safe against:
retried requests (client timeout, not malicious), two identical retries
racing each other, and two different concurrent requests racing on the same
wallet.

## Requirements

`wallets/exceptions.py` (extend the file from step 4): add
`InsufficientFunds`, `IdempotencyKeyConflict` (same key, different payload),
and `InvalidAmount`.

`wallets/services.py`:

- `deposit(tenant, wallet_id, amount, idempotency_key, request_hash) -> Transaction`
- `withdraw(tenant, wallet_id, amount, idempotency_key, request_hash) -> Transaction`

Both functions must, in this order:

1. Validate `amount > 0` up front — raise `InvalidAmount` before touching
   the database at all.
2. Check for an existing `Transaction` with `(tenant, idempotency_key)`.
   - If found and its stored request hash matches `request_hash`: return
     the existing transaction immediately. Do not re-run any of the steps
     below. This is what makes a client retry after a lost response safe.
   - If found with a *different* request hash: raise
     `IdempotencyKeyConflict`. (Store `request_hash` as a field on
     `Transaction` if it isn't there yet — add a migration.)
   - If not found, continue.
3. Open `transaction.atomic()`. Inside it, `select_for_update()` the
   `Wallet` row (via `get_wallet_for_tenant` from `selectors.py` — do not
   duplicate that lookup logic here).
4. For `withdraw` only: re-check `cached_balance >= amount` *after*
   acquiring the lock, not before — the whole point of the lock is that the
   balance you saw before acquiring it might already be stale. Raise
   `InsufficientFunds` if it fails, and let the `atomic()` block roll back
   with nothing written.
5. Create the `Transaction` row (`type=DEPOSIT` or `WITHDRAW`,
   `status=COMPLETED`, the `idempotency_key` and `request_hash`) and update
   `cached_balance` — both inside the same atomic block.
6. Rely on the database's `UniqueConstraint` on `(tenant, idempotency_key)`
   from step 2 as the real safety net for two identical retries racing each
   other: catch the resulting `IntegrityError` from step 3's insert, and on
   that specific error, re-fetch and return the transaction the *other*
   concurrent request just created, rather than treating it as a hard
   failure. This is what step 2's lookup alone cannot guarantee — the
   lookup and the insert are not atomic with each other unless you handle
   the race explicitly like this.

Do not implement this as "check if key exists, if not, proceed" without the
`IntegrityError` handling in step 6 — that check-then-act pattern has a gap
that two simultaneous retries can both slip through.

## Acceptance criteria

- [ ] A test asserts withdrawing more than the balance raises
      `InsufficientFunds` and leaves `cached_balance` and the transaction
      count completely unchanged.
- [ ] A test asserts calling `deposit` twice with the same idempotency key
      and the same amount returns the same `Transaction` both times and
      only increases the balance once.
- [ ] A test asserts calling `deposit` twice with the same idempotency key
      but a *different* amount raises `IdempotencyKeyConflict`.
- [ ] A concurrency test (threads, or Django's `TransactionTestCase` with
      two overlapping calls) proves two simultaneous withdrawals that would
      individually succeed but together overdraw the wallet result in
      exactly one success and one `InsufficientFunds` — never both
      succeeding.
- [ ] Neither function ever reads `cached_balance` outside of a
      `select_for_update()`-locked block when that read informs a decision.

Commit as `feat: implement idempotent, concurrency-safe deposit and withdraw`.
