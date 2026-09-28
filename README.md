# Cashless Wallet API

A multi-tenant REST API built with **Django + Django REST Framework** and backed by **PostgreSQL**. Each tenant is an isolated organisation with its own customers and wallets. The API supports creating customers, depositing and withdrawing funds, transferring between wallets, and reading balances and paginated transaction history — all idempotent, concurrency-safe, and tenant-scoped.

---

## Local Setup

**Prerequisites:** Python 3.11+, PostgreSQL running locally.

```bash
# 1. Clone the repository
git clone https://github.com/Ranger-DRAX/cashlessAi-assesment.git
cd cashlessAi-assesment

# 2. Create and activate a virtual environment
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create the database
psql -U postgres -c "CREATE DATABASE cashless_wallet;"

# 5. Configure environment variables
cp .env.example .env
# Edit .env and set DB_PASSWORD (and DJANGO_SECRET_KEY for production)

# 6. Apply migrations
python manage.py migrate

# 7. Start the development server
python manage.py runserver
```

The API is now available at `http://localhost:8000/api/`.

### Getting a tenant API key

Create a tenant via the API (no authentication required):

```bash
curl -s -X POST http://localhost:8000/api/tenants/ \
  -H "Content-Type: application/json" \
  -d '{"name": "My Company"}' | python -m json.tool
```

The response includes `"api_key"`. Save it — this is the only time it is returned. Use it in subsequent requests as:

```
Authorization: Api-Key <your_api_key>
```

---

## API Reference & curl Examples

All mutating endpoints require an `idempotency_key` field (or `Idempotency-Key` header). Using the same key + same payload is safe to retry; the same key with different payload returns `409 Conflict`.

### Create a tenant

```bash
curl -X POST http://localhost:8000/api/tenants/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Inc"}'
```

### Create a customer (+ wallet)

One call creates both a `Customer` and their initial `Wallet` (balance 0).

```bash
export API_KEY="<your_api_key>"

curl -X POST http://localhost:8000/api/customers/ \
  -H "Authorization: Api-Key $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "email": "alice@example.com"}'
```

Save the returned `wallet_id` as `WALLET_ID`.

```bash
export WALLET_ID="<alice_wallet_id>"
```

Create a second customer for transfer testing:

```bash
curl -X POST http://localhost:8000/api/customers/ \
  -H "Authorization: Api-Key $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"username": "bob", "email": "bob@example.com"}'
```

Save bob's `wallet_id` as `BOB_WALLET_ID`.

```bash
export BOB_WALLET_ID="<bob_wallet_id>"
```

### Deposit funds

```bash
curl -X POST http://localhost:8000/api/wallets/$WALLET_ID/deposit/ \
  -H "Authorization: Api-Key $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": 10000, "idempotency_key": "dep-001"}'
```

### Withdraw funds

```bash
curl -X POST http://localhost:8000/api/wallets/$WALLET_ID/withdraw/ \
  -H "Authorization: Api-Key $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": 2000, "idempotency_key": "wd-001"}'
```

Returns `402 Payment Required` with `"error": "insufficient_funds"` if the balance is too low.

### Transfer funds

```bash
curl -X POST http://localhost:8000/api/wallets/transfer/ \
  -H "Authorization: Api-Key $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"from_wallet_id\": \"$WALLET_ID\", \"to_wallet_id\": \"$BOB_WALLET_ID\", \"amount\": 3000, \"idempotency_key\": \"xfer-001\"}"
```

### Get wallet balance

```bash
curl http://localhost:8000/api/wallets/$WALLET_ID/balance/ \
  -H "Authorization: Api-Key $API_KEY"
```

### Get transaction history (paginated)

```bash
curl "http://localhost:8000/api/wallets/$WALLET_ID/transactions/" \
  -H "Authorization: Api-Key $API_KEY"
```

Returns cursor-paginated results (newest first). Follow `"next"` to get older pages.

---

## Error Shape

Every error response (including validation errors) follows one consistent shape:

```json
{
  "error": "snake_case_code",
  "detail": "Human-readable message or validation detail object"
}
```

| Status | `error` code | Trigger |
|--------|-------------|---------|
| 400 | `invalid_amount` | Amount ≤ 0 |
| 400 | `same_wallet_transfer` | `from_wallet_id == to_wallet_id` |
| 400 | `validation_error` | DRF serializer failure |
| 401 | `not_authenticated` | Missing or invalid `Api-Key` header |
| 402 | `insufficient_funds` | Balance < requested withdrawal/transfer |
| 404 | `wallet_not_found` | Wallet doesn't exist or belongs to another tenant |
| 409 | `idempotency_key_conflict` | Same key reused with different payload |

---

## Running the Test Suite

```bash
# Run all tests
python manage.py test

# Run with coverage
pip install coverage
coverage run manage.py test
coverage report
coverage html   # opens htmlcov/index.html for a visual report
```

---

## Trade-offs and Assumptions

### `cached_balance` vs. always summing the ledger

`cached_balance` is a denormalised convenience column — it exists alongside the immutable `Transaction` ledger so that balance reads are O(1) instead of O(n). The trade-off is that they must be kept in sync: every code path that writes a `Transaction` must also update `cached_balance` inside the **same `transaction.atomic()` block**. If they ever disagree (e.g. after a bug), the ledger is the authoritative source and `cached_balance` can be recomputed. The benefit is that high-traffic balance reads never need to aggregate millions of transaction rows.

### Idempotency-key uniqueness scope

Idempotency keys are scoped **per tenant**, not globally. The `UniqueConstraint` is on `(tenant, idempotency_key)`, not just `idempotency_key`. This means two different tenants can legitimately use the same key string without collision — which is the correct behaviour, since tenants are fully isolated and their client-side key generation is independent. The trade-off is that keys don't need to be UUIDs; short strings like `"dep-001"` work, as long as the client keeps them unique within its own key space.

### Pagination style: cursor vs. page-number

Cursor pagination was chosen over page-number pagination for two reasons. First, the transaction ledger is append-only — rows are never updated or deleted — making cursor-based navigation stable and consistent. With page-number pagination, a new deposit arriving between page 1 and page 2 would shift every subsequent row, causing duplicates or skips across pages. Second, cursor pagination scales better on large datasets because it doesn't require `OFFSET N` scans.

### One wallet per customer

The spec says "create a customer and their wallet" in a single call, which implies a 1:1 customer-to-wallet relationship. The data model does allow multiple wallets per customer (the FK is from `Wallet` to `Customer`, not the reverse), so nothing prevents extending the API later to create additional wallets or to specify a currency. For now, the `POST /api/customers/` endpoint creates exactly one default `BDT` wallet.

### Concurrency and deadlock prevention

`withdraw` and `transfer` acquire row-level locks via `SELECT FOR UPDATE` inside `transaction.atomic()`. Transfer locks **both** wallets in a globally consistent order (sorted UUID) to prevent the classic A→B / B→A deadlock. An additional safety net: a `UniqueConstraint` on `(tenant, idempotency_key)` catches the race where two simultaneous retries both pass the pre-insert idempotency check; the losing request catches the resulting `IntegrityError` and returns the winner's transaction instead of failing.

### `request_hash` for idempotency conflict detection

The `request_hash` field stores a SHA-256 hash of the validated request payload. This lets the server detect when a client reuses an idempotency key with a different payload (`409 Conflict`) vs. an identical retry (safe replay). Hashing the payload rather than storing it raw keeps the field size bounded and avoids storing potentially sensitive data redundantly.
