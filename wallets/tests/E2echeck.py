#!/usr/bin/env python3
"""End-to-end check for the Cashless Wallet API.

Runs a scripted scenario against a live server and prints one PASS / FAIL /
SKIP line per check, followed by a summary. Standard library only.

Usage:
    python scripts/e2e_check.py
    python scripts/e2e_check.py --base-url http://localhost:8000
    python scripts/e2e_check.py --skip-concurrency

Every run creates fresh tenants, customers and idempotency keys (suffixed with
a random run id), so it can be repeated against the same database.

Exit code: 0 = nothing failed, 1 = at least one check failed,
2 = the script could not run (server unreachable or a setup request failed).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

# Signed effect of each ledger row type on a wallet balance.
LEDGER_SIGN = {
    "deposit": 1,
    "transfer_credit": 1,
    "withdraw": -1,
    "transfer_debit": -1,
}


# Extra attempts after a connection reset/refusal (see Api.call).
CONNECT_RETRIES = 3


class SetupError(Exception):
    """Raised when a request needed to set up a scenario fails."""


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------


@dataclass
class Response:
    status: int
    json: Any
    text: str

    @property
    def body(self) -> dict[str, Any]:
        return self.json if isinstance(self.json, dict) else {}

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def describe(self) -> str:
        return f"HTTP {self.status} {self.text[:160]!r}"


class Api:
    """Thin client for the wallet API."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def call(
        self,
        method: str,
        path: str,
        *,
        key: str | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        url = path if path.startswith("http") else self.base_url + path
        request_headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if key is not None:
            request_headers["Authorization"] = f"Api-Key {key}"
        request_headers.update(headers or {})
        request = urllib.request.Request(
            url, data=data, method=method, headers=request_headers
        )
        # Connection resets happen when many parallel requests hit a dev
        # server with a small accept queue. Retrying is safe here because every
        # mutating request carries an idempotency key, so a retry that reaches
        # the server twice is a replay, never a second charge.
        for attempt in range(CONNECT_RETRIES + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    status, raw = resp.status, resp.read()
                break
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read()
                break
            except (ConnectionError, urllib.error.URLError) as exc:
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                if isinstance(reason, ConnectionError) and attempt < CONNECT_RETRIES:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise
        text = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        return Response(status, parsed, text)

    def create_tenant(self, name: str) -> Response:
        return self.call("POST", "/api/tenants/", body={"name": name})

    def create_customer(self, key: str, username: str) -> Response:
        body = {"username": username, "email": f"{username}@example.com"}
        return self.call("POST", "/api/customers/", key=key, body=body)

    def money(
        self,
        kind: str,
        key: str | None,
        wallet_id: str,
        amount: Any,
        idem: str | None,
        headers: dict[str, str] | None = None,
        omit_amount: bool = False,
    ) -> Response:
        body: dict[str, Any] = {}
        if not omit_amount:
            body["amount"] = amount
        if idem is not None:
            body["idempotency_key"] = idem
        return self.call(
            "POST",
            f"/api/wallets/{wallet_id}/{kind}/",
            key=key,
            body=body,
            headers=headers,
        )

    def transfer(
        self, key: str | None, src: Any, dst: Any, amount: Any, idem: str | None
    ) -> Response:
        body: dict[str, Any] = {
            "from_wallet_id": src,
            "to_wallet_id": dst,
            "amount": amount,
        }
        if idem is not None:
            body["idempotency_key"] = idem
        return self.call("POST", "/api/wallets/transfer/", key=key, body=body)

    def balance(self, key: str | None, wallet_id: str) -> Response:
        return self.call("GET", f"/api/wallets/{wallet_id}/balance/", key=key)

    def history(self, key: str | None, wallet_id: str) -> Response:
        return self.call("GET", f"/api/wallets/{wallet_id}/transactions/", key=key)

    def pages(self, key: str, first: Response, max_pages: int = 500) -> list[list[dict]]:
        """Follow ``next`` links starting from an already fetched first page."""
        pages: list[list[dict]] = []
        page = first
        for _ in range(max_pages):
            if not page.ok:
                raise SetupError(f"history page failed: {page.describe()}")
            pages.append(list(page.body.get("results") or []))
            next_url = page.body.get("next")
            if not next_url:
                return pages
            page = self.call("GET", next_url, key=key)
        raise SetupError("history pagination did not terminate")

    def full_history(self, key: str, wallet_id: str) -> list[dict]:
        pages = self.pages(key, self.history(key, wallet_id))
        return [row for page in pages for row in page]


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def section(self, title: str) -> None:
        print(f"\n== {title}", flush=True)

    def info(self, text: str) -> None:
        print(f"  INFO  {text}", flush=True)

    def _add(self, status: str, name: str, detail: str) -> None:
        self.rows.append((status, name, detail))
        line = f"  {status:<4}  {name}"
        if detail and status != "PASS":
            line += f"\n          {detail}"
        print(line, flush=True)

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        self._add("PASS" if condition else "FAIL", name, detail)
        return bool(condition)

    def skip(self, name: str, reason: str) -> None:
        self._add("SKIP", name, reason)

    def summary(self) -> int:
        passed = sum(1 for status, _, _ in self.rows if status == "PASS")
        failed = [(name, detail) for status, name, detail in self.rows if status == "FAIL"]
        skipped = [(name, detail) for status, name, detail in self.rows if status == "SKIP"]
        print("\n" + "=" * 60)
        print(f"PASS {passed}   FAIL {len(failed)}   SKIP {len(skipped)}")
        if failed:
            print("\nFailed checks:")
            for name, _ in failed:
                print(f"  - {name}")
        if skipped:
            print("\nNot executed:")
            for name, reason in skipped:
                print(f"  - {name}: {reason}")
        print("=" * 60)
        return 1 if failed else 0


@dataclass
class Ctx:
    api: Api
    report: Report
    args: argparse.Namespace
    run_id: str
    key_a: str = ""
    key_b: str = ""
    arafat: str = ""
    rahim: str = ""
    karim: str = ""
    tracked: list[tuple[str, str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def require(resp: Response, what: str) -> Response:
    if not resp.ok:
        raise SetupError(f"{what} failed: {resp.describe()}")
    return resp


def idem(ctx: Ctx, label: str) -> str:
    return f"{label}-{ctx.run_id}-{uuid.uuid4().hex[:6]}"


def new_customer(ctx: Ctx, key: str, username: str, label: str) -> str:
    resp = require(
        ctx.api.create_customer(key, f"{username}-{ctx.run_id}"),
        f"create customer {username}",
    )
    wallet_id = resp.body.get("wallet_id")
    if not wallet_id:
        raise SetupError(f"customer response has no wallet_id: {resp.describe()}")
    ctx.tracked.append((label, key, wallet_id))
    return wallet_id


def fund(ctx: Ctx, key: str, wallet_id: str, amount: int, label: str) -> None:
    require(ctx.api.money("deposit", key, wallet_id, amount, idem(ctx, label)), label)


def balance_of(ctx: Ctx, key: str, wallet_id: str) -> int | None:
    return ctx.api.balance(key, wallet_id).body.get("balance")


def ledger_total(rows: list[dict]) -> tuple[int, list[str]]:
    total, unknown = 0, []
    for row in rows:
        sign = LEDGER_SIGN.get(row.get("type"))
        if sign is None:
            unknown.append(str(row.get("type")))
            continue
        total += sign * int(row["amount"])
    return total, unknown


def status_counts(results: list[Any]) -> str:
    counts: dict[str, int] = {}
    for item in results:
        label = str(item.status) if isinstance(item, Response) else type(item).__name__
        counts[label] = counts.get(label, 0) + 1
    return ", ".join(f"{label} x{count}" for label, count in sorted(counts.items()))


def expect_error(
    report: Report, name: str, resp: Response, status: int, code: str | None = None
) -> bool:
    problems = []
    if resp.status != status:
        problems.append(f"expected HTTP {status}, got {resp.status}")
    if not ("error" in resp.body and "detail" in resp.body):
        problems.append("body is not {error, detail}")
    if code is not None and resp.body.get("error") != code:
        problems.append(f"expected error={code!r}, got {resp.body.get('error')!r}")
    detail = ""
    if problems:
        detail = "; ".join(problems) + " | " + resp.describe()
    return report.check(name, not problems, detail)


def run_parallel(
    calls: list[Callable[[], Response]], timeout: float = 120.0
) -> tuple[list[Any], bool]:
    """Run calls in threads released together by a barrier.

    Returns (results, hung). A result is a Response or the exception raised.
    """
    barrier = threading.Barrier(len(calls))
    results: list[Any] = [None] * len(calls)

    def worker(index: int, fn: Callable[[], Response]) -> None:
        try:
            barrier.wait(timeout=30)
            results[index] = fn()
        except Exception as exc:  # noqa: BLE001 - reported in the results
            results[index] = exc

    threads = [
        threading.Thread(target=worker, args=(i, fn), daemon=True)
        for i, fn in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    return results, any(thread.is_alive() for thread in threads)


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------


def scenario_setup(ctx: Ctx) -> None:
    api, report = ctx.api, ctx.report
    report.section("Setup: two tenants, three customers")
    tenant_a = require(api.create_tenant(f"Tenant A {ctx.run_id}"), "create tenant A")
    tenant_b = require(api.create_tenant(f"Tenant B {ctx.run_id}"), "create tenant B")
    ctx.key_a = tenant_a.body.get("api_key") or ""
    ctx.key_b = tenant_b.body.get("api_key") or ""
    if not ctx.key_a or not ctx.key_b:
        raise SetupError("tenant response has no api_key")
    report.check("Two tenants created with distinct API keys", ctx.key_a != ctx.key_b)

    ctx.arafat = new_customer(ctx, ctx.key_a, "arafat", "Arafat (tenant A)")
    ctx.rahim = new_customer(ctx, ctx.key_a, "rahim", "Rahim (tenant A)")
    ctx.karim = new_customer(ctx, ctx.key_b, "karim", "Karim (tenant B)")
    report.check(
        "Each customer gets a wallet starting at balance 0",
        all(
            balance_of(ctx, key, wallet) == 0
            for key, wallet in (
                (ctx.key_a, ctx.arafat),
                (ctx.key_a, ctx.rahim),
                (ctx.key_b, ctx.karim),
            )
        ),
    )


def scenario_core_flow(ctx: Ctx) -> None:
    api, report, ka = ctx.api, ctx.report, ctx.key_a
    report.section("Core flow: deposit, transfer, replay, conflict, insufficient funds")

    dep = api.money("deposit", ka, ctx.arafat, 10000, idem(ctx, "dep"))
    report.check(
        "Deposit 10000 into Arafat",
        dep.ok
        and dep.body.get("type") == "deposit"
        and dep.body.get("amount") == 10000
        and dep.body.get("status") == "completed",
        dep.describe(),
    )

    xfer_key = idem(ctx, "xfer")
    xfer = api.transfer(ka, ctx.arafat, ctx.rahim, 3000, xfer_key)
    debit = xfer.body.get("debit") or {}
    report.check(
        "Transfer 3000 Arafat -> Rahim succeeds and returns the debit row",
        xfer.ok and debit.get("type") == "transfer_debit" and debit.get("amount") == 3000,
        xfer.describe(),
    )
    got = (balance_of(ctx, ka, ctx.arafat), balance_of(ctx, ka, ctx.rahim))
    report.check("Balances are Arafat 7000, Rahim 3000", got == (7000, 3000), f"got {got}")

    rows_before = len(api.full_history(ka, ctx.arafat))
    replay = api.transfer(ka, ctx.arafat, ctx.rahim, 3000, xfer_key)
    report.info(f"first transfer HTTP {xfer.status}, replay HTTP {replay.status}")
    report.check("Replay of the same transfer succeeds", replay.ok, replay.describe())
    report.check(
        "Replay returns the same response body",
        replay.json == xfer.json,
        f"first={xfer.text[:120]!r} replay={replay.text[:120]!r}",
    )
    got = (balance_of(ctx, ka, ctx.arafat), balance_of(ctx, ka, ctx.rahim))
    report.check("Replay leaves balances unchanged", got == (7000, 3000), f"got {got}")
    rows_after = len(api.full_history(ka, ctx.arafat))
    report.check(
        "Replay writes no new ledger rows",
        rows_after == rows_before,
        f"rows {rows_before} -> {rows_after}",
    )

    conflict = api.transfer(ka, ctx.arafat, ctx.rahim, 3500, xfer_key)
    expect_error(
        report,
        "Same key with a different amount returns 409 idempotency_key_conflict",
        conflict,
        409,
        "idempotency_key_conflict",
    )
    got = (balance_of(ctx, ka, ctx.arafat), balance_of(ctx, ka, ctx.rahim))
    report.check("Conflict leaves balances unchanged", got == (7000, 3000), f"got {got}")
    rows_after = len(api.full_history(ka, ctx.arafat))
    report.check(
        "Conflict writes no new ledger rows",
        rows_after == rows_before,
        f"rows {rows_before} -> {rows_after}",
    )

    too_much = api.money("withdraw", ka, ctx.arafat, 999_999, idem(ctx, "wd-big"))
    expect_error(
        report,
        "Excessive withdrawal returns 402 insufficient_funds",
        too_much,
        402,
        "insufficient_funds",
    )
    report.check(
        "Rejected withdrawal leaves the balance at 7000",
        balance_of(ctx, ka, ctx.arafat) == 7000,
    )
    rows_after = len(api.full_history(ka, ctx.arafat))
    report.check(
        "Rejected withdrawal writes no ledger row",
        rows_after == rows_before,
        f"rows {rows_before} -> {rows_after}",
    )

    wd = api.money("withdraw", ka, ctx.arafat, 1000, idem(ctx, "wd"))
    report.check(
        "Valid withdrawal of 1000 succeeds",
        wd.ok and wd.body.get("type") == "withdraw" and wd.body.get("amount") == 1000,
        wd.describe(),
    )
    report.check(
        "Arafat is at 6000 and total across both wallets is 9000",
        (balance_of(ctx, ka, ctx.arafat), balance_of(ctx, ka, ctx.rahim)) == (6000, 3000),
    )

    arafat_rows = api.full_history(ka, ctx.arafat)
    types = sorted(row.get("type", "") for row in arafat_rows)
    report.check(
        "Arafat history has exactly deposit, transfer_debit, withdraw",
        types == ["deposit", "transfer_debit", "withdraw"],
        f"types={types}",
    )
    stamps = [row.get("created_at", "") for row in arafat_rows]
    report.check(
        "History is newest first",
        stamps == sorted(stamps, reverse=True),
        f"created_at order: {stamps}",
    )

    debit_row = next((r for r in arafat_rows if r.get("type") == "transfer_debit"), {})
    rahim_rows = api.full_history(ka, ctx.rahim)
    credit_row = next((r for r in rahim_rows if r.get("type") == "transfer_credit"), {})
    report.check(
        "Transfer wrote exactly two linked rows with equal amounts",
        bool(debit_row)
        and bool(credit_row)
        and debit_row.get("related_transaction_id") == credit_row.get("id")
        and credit_row.get("related_transaction_id") == debit_row.get("id")
        and debit_row.get("amount") == credit_row.get("amount") == 3000,
        f"debit={debit_row} credit={credit_row}",
    )


def scenario_idempotency(ctx: Ctx) -> None:
    api, report, ka, kb = ctx.api, ctx.report, ctx.key_a, ctx.key_b
    report.section("Idempotency: header key, key length, key scoped per tenant")

    header_key = idem(ctx, "hdr")
    before = balance_of(ctx, ka, ctx.rahim)
    first = api.money("deposit", ka, ctx.rahim, 100, None, {"Idempotency-Key": header_key})
    report.check(
        "Idempotency-Key header alone is accepted",
        first.ok and first.body.get("idempotency_key") == header_key,
        first.describe(),
    )
    again = api.money("deposit", ka, ctx.rahim, 100, None, {"Idempotency-Key": header_key})
    report.check(
        "Replay with the header key returns the same transaction",
        again.ok and again.body.get("id") == first.body.get("id"),
        again.describe(),
    )
    report.check(
        "Header-key deposit applied exactly once",
        balance_of(ctx, ka, ctx.rahim) == (before or 0) + 100,
    )

    long_key = "x" * 300
    too_long = api.money("deposit", ka, ctx.rahim, 100, None, {"Idempotency-Key": long_key})
    expect_error(report, "A 300-character header key is rejected with 400", too_long, 400)

    shared = f"shared-{ctx.run_id}"
    dep_a = api.money("deposit", ka, ctx.rahim, 50, shared)
    dep_b = api.money("deposit", kb, ctx.karim, 50, shared)
    report.check(
        "The same key string in two tenants does not collide",
        dep_a.ok and dep_b.ok and dep_a.body.get("id") != dep_b.body.get("id"),
        f"A: {dep_a.describe()} | B: {dep_b.describe()}",
    )


def _normalize(resp: Response, wallet_id: str) -> tuple[Any, Any, str]:
    detail = str(resp.body.get("detail", "")).replace(wallet_id, "<id>")
    return resp.status, resp.body.get("error"), detail


def scenario_isolation(ctx: Ctx) -> None:
    api, report, ka, kb = ctx.api, ctx.report, ctx.key_a, ctx.key_b
    report.section("Tenant isolation: cross-tenant access is a generic 404")

    snapshot_before = (
        balance_of(ctx, ka, ctx.arafat),
        balance_of(ctx, ka, ctx.rahim),
        balance_of(ctx, kb, ctx.karim),
    )
    rows_before = (
        len(api.full_history(ka, ctx.arafat)),
        len(api.full_history(ka, ctx.rahim)),
        len(api.full_history(kb, ctx.karim)),
    )

    def attempts(key: str, foreign: str, own: str) -> dict[str, Callable[[str], Response]]:
        return {
            "read balance": lambda w: api.balance(key, w),
            "read history": lambda w: api.history(key, w),
            "deposit": lambda w: api.money("deposit", key, w, 100, idem(ctx, "iso")),
            "withdraw": lambda w: api.money("withdraw", key, w, 100, idem(ctx, "iso")),
            "transfer to it": lambda w: api.transfer(key, own, w, 100, idem(ctx, "iso")),
            "transfer from it": lambda w: api.transfer(key, w, own, 100, idem(ctx, "iso")),
        }

    for label, key, foreign, own in (
        ("Tenant A key vs Karim's wallet", ka, ctx.karim, ctx.arafat),
        ("Tenant B key vs Arafat's wallet", kb, ctx.arafat, ctx.karim),
    ):
        unknown = str(uuid.uuid4())
        for action, run in attempts(key, foreign, own).items():
            foreign_resp = run(foreign)
            unknown_resp = run(unknown)
            report.check(
                f"{label}: {action} returns 404",
                foreign_resp.status == 404,
                foreign_resp.describe(),
            )
            report.check(
                f"{label}: {action} looks identical to a nonexistent wallet",
                _normalize(foreign_resp, foreign) == _normalize(unknown_resp, unknown),
                f"foreign={foreign_resp.describe()} unknown={unknown_resp.describe()}",
            )

    snapshot_after = (
        balance_of(ctx, ka, ctx.arafat),
        balance_of(ctx, ka, ctx.rahim),
        balance_of(ctx, kb, ctx.karim),
    )
    rows_after = (
        len(api.full_history(ka, ctx.arafat)),
        len(api.full_history(ka, ctx.rahim)),
        len(api.full_history(kb, ctx.karim)),
    )
    report.check(
        "No balance changed after all cross-tenant attempts",
        snapshot_before == snapshot_after,
        f"{snapshot_before} -> {snapshot_after}",
    )
    report.check(
        "No ledger rows were written by cross-tenant attempts",
        rows_before == rows_after,
        f"{rows_before} -> {rows_after}",
    )


def scenario_auth_validation(ctx: Ctx) -> None:
    api, report, ka = ctx.api, ctx.report, ctx.key_a
    report.section("Authentication and input validation")
    rahim_before = balance_of(ctx, ka, ctx.rahim)

    calls: dict[str, Callable[[str | None], Response]] = {
        "POST customers": lambda k: api.create_customer(k, f"nokey-{ctx.run_id}"),
        "POST deposit": lambda k: api.money("deposit", k, ctx.rahim, 1, idem(ctx, "auth")),
        "POST withdraw": lambda k: api.money("withdraw", k, ctx.rahim, 1, idem(ctx, "auth")),
        "POST transfer": lambda k: api.transfer(k, ctx.rahim, ctx.arafat, 1, idem(ctx, "auth")),
        "GET balance": lambda k: api.balance(k, ctx.rahim),
        "GET history": lambda k: api.history(k, ctx.rahim),
    }
    for name, run in calls.items():
        expect_error(report, f"{name}: no API key returns 401", run(None), 401)
        expect_error(report, f"{name}: invalid API key returns 401", run("not-a-real-key"), 401)

    amount_cases: list[tuple[str, Any]] = [
        ("amount 0", 0),
        ("negative amount", -5),
        ("float 10.5", 10.5),
        ("float 100.0", 100.0),
        ("numeric string '100'", "100"),
        ("boolean true", True),
        ("null amount", None),
        ("amount above bigint max", 2**63),
    ]
    for label, value in amount_cases:
        resp = api.money("deposit", ka, ctx.rahim, value, idem(ctx, "val"))
        expect_error(report, f"Deposit with {label} returns 400", resp, 400)
    expect_error(
        report,
        "Deposit with no amount returns 400",
        api.money("deposit", ka, ctx.rahim, None, idem(ctx, "val"), omit_amount=True),
        400,
    )
    expect_error(
        report,
        "Deposit with no idempotency key returns 400",
        api.money("deposit", ka, ctx.rahim, 1, None),
        400,
    )
    expect_error(
        report,
        "Deposit with an empty idempotency key returns 400",
        api.money("deposit", ka, ctx.rahim, 1, ""),
        400,
    )
    expect_error(
        report,
        "Withdraw of amount 0 returns 400",
        api.money("withdraw", ka, ctx.rahim, 0, idem(ctx, "val")),
        400,
    )
    expect_error(
        report,
        "Transfer to the same wallet returns 400 same_wallet_transfer",
        api.transfer(ka, ctx.rahim, ctx.rahim, 1, idem(ctx, "val")),
        400,
        "same_wallet_transfer",
    )
    expect_error(
        report,
        "Transfer with a malformed wallet id returns 400",
        api.transfer(ka, "not-a-uuid", ctx.rahim, 1, idem(ctx, "val")),
        400,
    )
    expect_error(
        report,
        "Transfer of amount 0 returns 400",
        api.transfer(ka, ctx.rahim, ctx.arafat, 0, idem(ctx, "val")),
        400,
    )

    bad_path = api.call("GET", "/api/wallets/not-a-uuid/balance/", key=ka)
    report.check(
        "Malformed wallet id in the URL returns 400 or 404, never 5xx",
        bad_path.status in (400, 404),
        bad_path.describe(),
    )
    unknown_url = api.call("GET", "/api/does-not-exist/", key=ka)
    report.check(
        "Unknown URL returns the JSON {error, detail} shape",
        "error" in unknown_url.body and "detail" in unknown_url.body,
        unknown_url.describe(),
    )
    report.check(
        "Rejected requests changed no balance",
        balance_of(ctx, ka, ctx.rahim) == rahim_before,
    )


def scenario_pagination(ctx: Ctx) -> None:
    api, report, ka = ctx.api, ctx.report, ctx.key_a
    count = ctx.args.history_count
    report.section(f"Pagination: {count} deposits, cursor walk, stability")

    wallet = new_customer(ctx, ka, "pager", "Pagination wallet")
    for i in range(count):
        require(api.money("deposit", ka, wallet, 1, idem(ctx, f"page-{i}")), "seed deposit")

    pages = api.pages(ka, api.history(ka, wallet))
    rows = [row for page in pages for row in page]
    ids = [row.get("id") for row in rows]
    report.check(f"History returns all {count} rows", len(ids) == count, f"got {len(ids)}")
    report.check("No duplicate rows across pages", len(set(ids)) == len(ids))
    stamps = [row.get("created_at", "") for row in rows]
    report.check("Rows are newest first across pages", stamps == sorted(stamps, reverse=True))
    if len(pages) < 2:
        report.skip(
            "History is actually split across pages",
            f"only one page returned; use --history-count above the page size (got {count})",
        )
        report.skip("Stability when a row is inserted between pages", "needs at least 2 pages")
    else:
        report.check(f"History is split across {len(pages)} pages", True)
        first = api.history(ka, wallet)
        require(api.money("deposit", ka, wallet, 1, idem(ctx, "page-new")), "insert deposit")
        rest = api.pages(ka, first)
        combined = [row.get("id") for page in rest for row in page]
        report.check(
            "Inserting a row between page fetches causes no duplicates or skips",
            len(set(combined)) == len(combined) and set(ids) <= set(combined),
            f"expected {len(ids)} original ids, got {len(combined)} rows "
            f"({len(set(combined))} unique)",
        )


def scenario_concurrency(ctx: Ctx) -> None:
    api, report, ka = ctx.api, ctx.report, ctx.key_a
    report.section("Concurrency: parallel requests released together")
    if ctx.args.skip_concurrency:
        for name in (
            "Concurrent withdrawals cannot overdraw",
            "Concurrent duplicate idempotency key applies once",
            "Opposing transfers do not deadlock",
        ):
            report.skip(name, "--skip-concurrency was set")
        return
    n = max(ctx.args.concurrency, 4)

    wallet = new_customer(ctx, ka, "race-withdraw", "Concurrent withdraw wallet")
    fund(ctx, ka, wallet, 10000, "race-fund")
    calls = [
        (lambda i=i: api.money("withdraw", ka, wallet, 3000, idem(ctx, f"race-wd-{i}")))
        for i in range(n)
    ]
    results, hung = run_parallel(calls)
    report.check("Concurrent withdrawals: no request hung", not hung)
    ok = [r for r in results if isinstance(r, Response) and r.ok]
    rejected = [r for r in results if isinstance(r, Response) and r.status == 402]
    expected_ok = min(n, 10000 // 3000)
    report.check(
        f"Exactly {expected_ok} of {n} withdrawals of 3000 succeed, the rest get 402",
        len(ok) == expected_ok and len(rejected) == n - expected_ok,
        f"statuses: {status_counts(results)}",
    )
    final = balance_of(ctx, ka, wallet)
    report.check(
        "Balance is never negative and matches the successful withdrawals",
        final == 10000 - 3000 * len(ok) and (final or 0) >= 0,
        f"balance={final}, successes={len(ok)}",
    )

    wallet = new_customer(ctx, ka, "race-dupkey", "Concurrent duplicate-key wallet")
    shared_key = idem(ctx, "race-dup")
    calls = [(lambda: api.money("deposit", ka, wallet, 500, shared_key)) for _ in range(n)]
    results, hung = run_parallel(calls)
    report.check("Duplicate-key race: no request hung", not hung)
    responses = [r for r in results if isinstance(r, Response)]
    tx_ids = {r.body.get("id") for r in responses if r.ok}
    report.check(
        f"All {n} racing requests with one key return the same transaction",
        len(responses) == n and all(r.ok for r in responses) and len(tx_ids) == 1,
        f"statuses: {status_counts(results)}, distinct transaction ids: {len(tx_ids)}",
    )
    report.check(
        "The deposit was applied exactly once (balance 500)",
        balance_of(ctx, ka, wallet) == 500,
    )

    p = new_customer(ctx, ka, "race-p", "Opposing transfers wallet P")
    q = new_customer(ctx, ka, "race-q", "Opposing transfers wallet Q")
    fund(ctx, ka, p, 10000, "race-fund-p")
    fund(ctx, ka, q, 10000, "race-fund-q")
    calls = []
    for i in range(n):
        calls.append(lambda i=i: api.transfer(ka, p, q, 100, idem(ctx, f"race-pq-{i}")))
        calls.append(lambda i=i: api.transfer(ka, q, p, 100, idem(ctx, f"race-qp-{i}")))
    results, hung = run_parallel(calls)
    report.check("Opposing transfers: no request hung", not hung)
    report.check(
        f"All {2 * n} opposing transfers complete without an error",
        all(isinstance(r, Response) and r.ok for r in results),
        f"statuses: {status_counts(results)}",
    )
    got = (balance_of(ctx, ka, p), balance_of(ctx, ka, q))
    report.check(
        "Opposing transfers net to zero and conserve the total",
        got == (10000, 10000),
        f"balances P,Q = {got}",
    )


def scenario_ledger_invariants(ctx: Ctx) -> None:
    api, report = ctx.api, ctx.report
    report.section("Ledger invariant: sum of ledger rows equals balance, every wallet")
    for label, key, wallet_id in ctx.tracked:
        rows = api.full_history(key, wallet_id)
        total, unknown = ledger_total(rows)
        balance = balance_of(ctx, key, wallet_id)
        report.check(
            f"Ledger sum equals balance: {label}",
            not unknown and total == balance,
            f"ledger={total} balance={balance} unknown types={unknown}",
        )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="End-to-end check for the wallet API.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--history-count",
        type=int,
        default=25,
        help="deposits to create for the pagination check (must exceed the page size)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="parallel requests per concurrency check (minimum 4)",
    )
    parser.add_argument("--skip-concurrency", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-request seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api = Api(args.base_url, args.timeout)
    report = Report()
    ctx = Ctx(api=api, report=report, args=args, run_id=uuid.uuid4().hex[:8])
    print(f"Base URL: {api.base_url}")
    print(f"Run id:   {ctx.run_id}")

    steps = [
        scenario_setup,
        scenario_core_flow,
        scenario_idempotency,
        scenario_isolation,
        scenario_auth_validation,
        scenario_pagination,
        scenario_concurrency,
        scenario_ledger_invariants,
    ]
    try:
        for step in steps:
            step(ctx)
    except SetupError as exc:
        print(f"\nCannot continue: {exc}")
        report.summary()
        return 2
    except OSError as exc:
        print(f"\nNetwork error talking to {api.base_url}: {exc}")
        return 2
    return report.summary()


if __name__ == "__main__":
    sys.exit(main())