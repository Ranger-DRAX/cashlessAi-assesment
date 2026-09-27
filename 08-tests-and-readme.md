# Step 8 — Write tests and the README

Read `AGENT.md` first. This step assumes steps 1–7 are complete and mostly
consolidates and fills gaps in tests written along the way, plus documents
the whole project for a reviewer who has never seen it before.

## Objective

A test suite that specifically proves every requirement in the original
brief's "what will be looking at" list, and a README that lets someone
clone the repo and have it running in under five minutes.

## Requirements

Review `tenants/tests/` and `wallets/tests/` (created incrementally in
earlier steps) and fill any gaps so the following are all explicitly
covered, each as its own named test — not folded into a bigger test that
obscures what actually failed if it breaks later:

- Withdrawing more than the balance is rejected and changes nothing.
- A concurrent pair of transfers (or withdrawals) racing on the same
  wallet(s) never overdraws it — use threads or Django's
  `TransactionTestCase` with real overlapping transactions, not mocks.
- Sending the same idempotency key twice: same payload returns the same
  result without double-processing; different payload returns `409`.
- A tenant cannot read another tenant's wallet balance or transaction
  history (expect `404`).
- A transfer between wallets in two different tenants is rejected.
- Creating a tenant, then a customer, then a wallet, then a full
  deposit → withdraw → transfer → balance → history happy-path flow works
  end to end.

Run `coverage run manage.py test && coverage report` and note the
percentage in your final summary — it doesn't need to be perfect, but any
file under roughly 80% should have a one-line explanation of what's
untested and why.

`README.md`, replacing the placeholder from step 1, with:

- One-paragraph project description.
- Setup: local virtualenv + Postgres steps, from a completely clean clone,
  including how to run migrations and how to get a tenant's API key for
  testing. (A Docker-based setup section gets added on top of this in step
  9, once the app is feature-complete — don't add Docker instructions here.)
- Example `curl` calls for at least: create tenant, create customer, deposit,
  withdraw, transfer, get balance, get history — including the
  `X-Tenant-ID`/API-key header and `Idempotency-Key` header on every
  mutating call.
- How to run the test suite.
- A "Trade-offs and assumptions" section, covering at minimum: why
  `cached_balance` exists alongside the ledger instead of always summing it,
  the idempotency-key uniqueness scope, the choice of pagination style, and
  anything else about the domain you had to assume rather than were told
  (e.g. one wallet per customer vs. multiple).

## Acceptance criteria

- [ ] Every bullet in the "what will be looking at" list above has a test
      that would fail if that specific guarantee were removed — verify this
      by mentally (or actually) breaking each guarantee once and confirming
      the corresponding test fails.
- [ ] The README's local setup steps, followed exactly on a clean clone
      with a fresh database, plus its `curl` examples run in order, work
      without modification.
- [ ] The README's trade-offs section reads like an explanation to a
      reviewer, not a restatement of the spec.

Commit as `test: cover core flows and concurrency; docs: add README`.
