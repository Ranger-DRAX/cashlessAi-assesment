# Cashless Wallet API

A multi-tenant REST API built with **Django + Django REST Framework** and backed by **PostgreSQL**. Each tenant is an isolated organisation with its own customers and wallets. The API supports creating customers, depositing and withdrawing funds, transferring between wallets, and reading balances and paginated transaction history — all idempotent, concurrency-safe, and tenant-scoped.

---

## Setup & Running

### Option 1: Run with Docker (Recommended)

**Prerequisites:** Docker and Docker Compose installed.

```bash
# 1. Clone the repository
git clone https://github.com/Ranger-DRAX/cashlessAi-assesment.git
cd cashlessAi-assesment

# 2. Build and start the entire stack (PostgreSQL + API + Auto-migrations)
docker compose up --build
```

The API is now running at `http://localhost:8000/api/` with database migrations automatically applied.

#### Running Tests with Docker:
```bash
# Run the 130 Django unit and integration tests:
docker compose exec web python manage.py test -v 2

# Run the 103 live end-to-end assertions:
docker compose exec web python E2echeck.py
```

---

### Option 2: Local Setup (without Docker)

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

The API is now available at `http://localhost:8000/api/` (Interactive Swagger docs: `http://localhost:8000/api/docs/`).

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

## Interactive Documentation (Swagger UI)

With the server running, open **[http://localhost:8000/api/docs/](http://localhost:8000/api/docs/)** in your browser.
- Full OpenAPI 3.0 schema with interactive request builders and documentation.
- Click the green **Authorize 🔓** button and enter your API key to test any endpoint directly from your browser.

---

## API Endpoints Reference

| Method | Endpoint | Auth Required | Description |
| :--- | :--- | :---: | :--- |
| `POST` | `/api/tenants/` | No | Register a new tenant organisation and receive an API key |
| `POST` | `/api/customers/` | Yes | Create a customer and default BDT wallet (balance 0) |
| `POST` | `/api/wallets/{id}/deposit/` | Yes | Deposit funds into a wallet (idempotent) |
| `POST` | `/api/wallets/{id}/withdraw/` | Yes | Withdraw funds from a wallet (rejects with 402 if balance insufficient) |
| `POST` | `/api/wallets/transfer/` | Yes | Atomically transfer funds between two wallets of the same tenant |
| `GET`  | `/api/wallets/{id}/balance/` | Yes | Get the current cached balance and currency |
| `GET`  | `/api/wallets/{id}/transactions/` | Yes | Get paginated transaction history (cursor-based, newest-first) |

### Key Guarantees
- **Idempotency**: All mutating endpoints (`deposit`, `withdraw`, `transfer`) require an idempotency key via the `"idempotency_key"` JSON field or `Idempotency-Key` HTTP header. Replaying with the same payload returns the original transaction receipt (`200 OK`); reusing the key with a different payload returns `409 Conflict`.
- **Strict Integer Amounts**: Amounts must be positive integers up to PostgreSQL `bigint` max (`9,223,372,036,854,775,807`). Floats and strings (e.g. `"100"`, `100.5`) are rejected with `400 Bad Request`.
- **Tenant Isolation**: Every query filters by `tenant=request.tenant`. Cross-tenant requests return generic `404 Not Found` to prevent resource existence enumeration.

---

## Verification & Testing

### 1. Automated Live End-to-End Suite (`E2echeck.py`)
With the server running (`python manage.py runserver`), run the cross-platform end-to-end verification script (pure Python standard library, zero extra dependencies):

```bash
# Option A: From your host machine (against http://localhost:8000)
python wallets/tests/E2echeck.py

# Option B: Inside Docker container
docker compose exec web python wallets/tests/E2echeck.py
```
*Executes **103 assertions** verifying the entire lifecycle, multi-tenant isolation, idempotency replay vs conflict, strict input validation, multi-threaded concurrency barriers, and ledger sum mathematical invariants.*

### 2. Django Unit & Integration Test Suite
Run the 130 internal test cases (runs against an isolated, automated test database — no dev server required):

```bash
# Local:
python manage.py test -v 2

# Docker:
docker compose exec web python manage.py test -v 2
```

### 3. Test Coverage Report
```bash
pip install coverage
coverage run manage.py test
coverage report
```

---

## Error Shape

Every error response (including validation errors) follows one consistent shape:

```json
{
  "error": "snake_case_code",
  "detail": "Human-readable message or validation detail object"
}
```

| Status | `error` code               | Trigger                                           |
| --------| ----------------------------| ---------------------------------------------------|
| 400    | `invalid_amount`           | Amount ≤ 0                                        |
| 400    | `same_wallet_transfer`     | `from_wallet_id == to_wallet_id`                  |
| 400    | `validation_error`         | DRF serializer failure                            |
| 401    | `not_authenticated`        | Missing or invalid `Api-Key` header               |
| 402    | `insufficient_funds`       | Balance < requested withdrawal/transfer           |
| 404    | `wallet_not_found`         | Wallet doesn't exist or belongs to another tenant |
| 409    | `idempotency_key_conflict` | Same key reused with different payload            |

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
