# Cloud finance journal API

Base path `/api/v1/finance`. JWT endpoints use existing read/write scope policies;
MCP tools `finance_operation` (mcp:write) and `finance_read` (mcp:read) call the same service.
Operations are user-owned, not ledger-scoped mobile sync entities. They never change
`initial_balance`, write fake income, overwrite historical events, or mutate `ledger_snapshot`.

## POST /events

Required header `Idempotency-Key` (1–255 chars). JSON `{ "kind": "...", "data": {...} }`.
Same key/payload returns the original event, changed payload returns 409. All writes serialize
per user and commit one atomic event (including all transfer legs); no partial transfer is possible.
Timestamps are timezone-aware ISO 8601; omitted `effective_at` means server current time.
Future postings are rejected. Monetary inputs should be decimal strings; journal values remain strings.

- `reconciliation`: `account_id,target_balance,expected_balance,effective_at,source,reason`,
  optional `difference_classification` = `missing_income|missing_expense|unknown` (default unknown).
  This classification is an audit annotation, **not** an income/expense posting.
  Computes before/after/difference in account currency and applies the difference to real cash balance.
  Stale expected balance, or inserting before a later reconciliation, returns 409.
- `reversal`: `event_id,reason` (optional effective_at). Supports reconciliation and transfer;
  appends the inverse effects, never deletes the original. Already reversed or later reconciled
  affected accounts return 409. Reverse later reconciliation first.
- `transfer`: `from_account_id,to_account_id,from_amount,to_amount,from_currency,to_currency,source,external_id`.
  Optional `fee_amount,fee_account_id,fee_currency`; fee must identify a same-currency owned account.
  Amounts are positive and independently specified in each account's own currency.
  `actual_exchange_rate=to_amount/from_amount` excludes separately identified fees.
  `(user,source,external_id)` deduplicates external transfers across different request keys (409).
- `receivable`: `amount,currency,counterparty,reason`. Recognizes a claim, no cash movement.
- `receivable_installment`: `receivable_id,amount,due_at`. Total installments cannot exceed principal.
- `repayment`: `receivable_id,amount,account_id`, optional `installment_id`. Partial and repeated payments
  supported; total and installment overpayment rejected. Increases cash without becoming income.
  Repayment currency is inherited from receivable and must match account currency.
- `snapshot`: optional `trigger` label and current `effective_at`. Captures **one immutable observation
  per user per UTC day**, including account cash and product holding values/quote timestamps.
  Existing day returns 409, except exact same-key replay returns original. Only current capture
  (within 5 minutes) is accepted: no fabricated backfill from today's mutable holdings.
- `investment_event`: `account_id,currency,amount,classification,source,reason`.
  Classification = `subscription,redemption,dividend_cash,dividend_reinvested,fee,tax,valuation_change,
  transfer_in,transfer_out,buy,sell,interest,funding_fee,realized_pnl`.
  valuation_change/realized_pnl/funding_fee accept signed amounts. These are sourced annotations,
  do not silently double-post cash or mutate product quantity.

Response for POST and each GET /events item:

```json
{"id":"uuid","kind":"reconciliation","effective_at":"ISO UTC","created_at":"ISO UTC",
 "payload":{"account_id":"a","target_balance":"120","expected_balance":"100",
 "before_balance":"100","after_balance":"120","difference":"20","currency":"CNY",
 "difference_classification":"unknown","source":"statement","reason":"observation"},
 "effects":{"a":"20"}}
```

`payload` also retains submitted data. HTTP errors: 404 foreign/missing account or reference,
409 duplicate/conflict/overpayment, 422 validation. All failures roll back.

## Reads and actual balance consumers

- `GET /balances`: object keyed by account sync ID. Each value:
  `{account_id,account_name,currency,cash_balance:number,balance_decimal:string,cash_as_of:ISO,balance_source:"projection_plus_finance_events"}`.
  Final balance = initial + visible nondeleted-ledger projection movements + finance effects.
  Uses account-original `amount`, never ledger-base `native_amount`.
  Missing legacy IDs resolve by unique account name only; ambiguous names never guessed.
- `GET /events`: original append-only event array.
- `GET /receivables`: receivable events plus `paid,remaining` decimal strings,
  `installments` (events with paid/remaining), `repayments` (events).
- `GET /period-report?start=ISO&end=ISO`: `opening_assets,closing_assets,asset_change` maps by currency
  when exact boundary snapshots exist, otherwise null. `investment_return,return_rate` remain null
  because complete priced-position/cashflow coverage is not established. Asset change is **not yield**.
  Includes classified events in `(start,end]`; no cross-currency nominal sums.

Existing `/read/workspace/accounts`, legacy net-worth cash history, MCP `list_accounts`, and investment
valuation cash services include the event effects. Income/expense totals still use ordinary projections.
REST and MCP writes broadcast a user `sync_change` invalidation after commit using the application's shared WebSocket manager.
Flutter must consume `/finance/balances` as final cloud cash (not add it to local balance), keep it read-only,
and label offline/stale observations; finance events deliberately do not masquerade as mobile transactions.

## Capture runtime and honest historical boundaries

An application-managed APScheduler task captures at **00:05 UTC daily**, enabled by default via
`FINANCE_SNAPSHOT_SCHEDULER_ENABLED=true`; set false to disable. On application startup a separate
one-shot task captures **only the current UTC day**. Missing previous days are never backfilled.
Each user receives an isolated database session/transaction; failures are logged and do not stop other
users. The journal's per-user write lock and `daily-snapshot:YYYY-MM-DD` receipt prevent duplicate
capture across workers/retries. A previous manual capture for that day wins and is never overwritten.
Shutdown waits for and closes scheduler threads. UTC day policy is explicit; client timezone does not
change uniqueness. Tests disable automatic scheduling globally and exercise the real job against an
in-memory factory. The runtime is configured in code, **not deployed or run against user data here**.

Snapshots are observations and cannot be overwritten via the API. Old account projections remain mutable
under existing mobile sync, so arbitrary reconstruction by effective_at can change after historical edits;
this is why reports require immutable exact-boundary captures and never claim reconstructed balances are
historical investment valuations. Existing net-worth history remains a reconstructed cash-only series using
its established FX behavior, not the new evidence-based period report. Initial balance changes or later
legacy sync edits are not prevented by this module; users should reconcile after such changes.

No live deployment, production migrations, or user-book mutation is performed by implementation/tests. The daily scheduler is configured and tested in isolation, not launched against the user's database here.
