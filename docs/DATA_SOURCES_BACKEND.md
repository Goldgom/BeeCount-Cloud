# Cloud read-only data sources

## REST provider

`binance_api` is a signed REST reader, not an exchange trading client. No order, withdrawal, redemption or transfer action endpoint is present. Endpoint names map to static method/host/path constants in `src/services/binance_source.py`. Caller input cannot supply a URL or command. Funding's **POST** `/sapi/v1/asset/get-funding-asset` is explicitly allowlisted as a read-only query; all other supported upstream requests are GET.

| Module | Upstream | Equity treatment |
|---|---|---|
| spot | `/api/v3/account` | free + locked, free separately available |
| funding | `/sapi/v1/asset/get-funding-asset` | free + locked + freeze + withdrawing |
| earn_flexible | `/sapi/v1/simple-earn/flexible/position` (paged) | totalAmount, not implied available |
| portfolio_margin | `/papi/v1/account`, `/papi/v1/balance` | accountEquity in **USD** authoritative; wallet details informational |
| PM positions | `/papi/v1/um/positionRisk`, `/papi/v1/cm/positionRisk` | quantity/notional/PnL informational, NEVER add notional to equity |
| usd_m_futures | `/fapi/v3/account` | asset marginBalance; no extra addition of positions |
| coin_m_futures | `/dapi/v1/account` | asset marginBalance; no extra addition of positions |

When PM is available, conventional futures are marked included_in_portfolio_margin and not fetched/added again. A 403/unsupported/malformed response is `unknown`, not a zero asset. Unknown module coverage makes authoritative totals null; known subtotals remain available. Conventional users without PM access intentionally have partial coverage rather than guessed zero PM assets. No spot margin/options/locked Earn completeness claim is made.

Raw amounts are Decimal strings. `balance`, `net_equity`, `available`, `unrealized_pnl` and positions are separate fields. Non-PM asset estimates use Binance asset/USDT prices; USDT is **not** assumed USD. PM `accountEquity` remains USD. Existing ConversionGraph resolves base valuations (including explicit user FX overrides); missing FX remains unknown. Base summaries use existing cent rounding; raw units remain precise.

`source_time` is Binance server time sampled at sync start, with explicit `source_time_status=exchange_server_time_at_sync_start_not_price_tick`. `observed_at` is local collection time. No claim of exchange streaming ticks is made.

## API

All endpoints require existing authenticated user and appropriate read/write scopes.

- GET `/api/v1/data-sources/providers`, `/accounts`, and base collection return `{items: [...]}`.
- POST base collection creates a source (name, provider, write-only credentials.api_key/api_secret, optional symbols, interval, paused, policy/account).
- PATCH `/{id}` updates configuration. DELETE `/{id}` deletes source, encrypted credentials, events and receipts.
- GET `/{id}` returns source details. POST `/{id}/sync` performs sync; optional `Idempotency-Key` (1..128 chars) replays without upstream requests.
- GET `/{id}/events?offset=0&limit=100` returns original upstream event payloads (max 500), after tenant ownership check.
- CLI/native arbitrary executable invocation is not supported. `binance_cli` advertises unavailable; a separately defined normalized JSON import can accept externally generated data without any cloud shell execution.

`coverage_policy=separate` requires account_id null. `replace_bound_account` requires a user's own UserAccountProjection sync_id. Only one replacing source may bind the account. The investment/all_assets read service excludes that account's manual cash/holdings and substitutes observed source equity, even when the source is unknown (no misleading fallback/double counting). No initial_balance, mobile projection or finance event is rewritten. Other accounts and manual unbound investments are preserved.

## History scope

`symbols` (up to 20 uppercase Binance pairs) is required for Spot myTrades. Requests use limit 1000, bounded <24h windows, then fromId pagination without start/end (incompatible combinations are not sent). Deposits, withdrawals, MAIN_UMFUTURE/UMFUTURE_MAIN transfer queries and BONUS/REALTIME/REWARDS flexible rewards are read. Event identifiers are unique per source/kind; reward events use deterministic canonical payload hashes where Binance provides no ID.

First sync starts at the previous 24h, **not full historical backfill**. Successful windows advance persistent per-kind cursors with boundary overlap. Capped/truncated pagination does not advance a cursor and reports unknown, never silent complete. Only two internal transfer directions are covered; remaining types explicitly report unknown. `history_coverage` is independent from balance module status.

## Security / execution

Fernet encrypts credentials with a domain-separated key derived from JWT_SECRET. Keep a stable protected deployment JWT_SECRET; rotating it requires credential re-entry. SecretStr protects repr; API responses never return secrets; source validation errors omit input/context. HTTP transport INFO logs are disabled to avoid signed URLs. Failures store static error codes, not upstream response bodies, exception repr or decrypted credentials.

Backend startup runs an asyncio scheduler; it inspects due sources every 15 seconds and respects paused state. Configured period is 60..86400 seconds (default 300). This is **near-real-time polling**, not real-time WebSocket exchange data. Only binance_api is polled. Each sync has an atomic database lease with fencing token, 15-minute expiry and a 600-second operation timeout; each request times out after 10s (connect 5s), up to three retries for timeout/network/429/418/5xx with bounded Retry-After/backoff. Requests are sequential and paced; Binance 429 remains authoritative. Multiple server workers share database leases.

## Verification and rollout

Migration: `0026_data_sources`, parent `0025_investment_valuation`. Run normal Alembic deployment migration before starting new code. Tests use real httpx request construction and MockTransport fixture responses, not real account data. `tests/test_data_sources.py` + `test_data_source_resilience.py` cover signatures, read-only POST allowlisting, partial/unknown coverage, PM exclusion of nominal positions, tenant CRUD, encrypted secrets and validation redaction, lease conflict, pause/delete, dedup/idempotency, retry/Retry-After and pagination truncation. Existing investment tests verify integration compatibility.

**Live account verification remains blocked until a user securely configures an IP-restricted read-only API key with the intended account capabilities.** No credentials were available during implementation. Do not claim the fixture suite proves live Binance account availability or production scheduler deployment.

## Standard JSON / external CLI bridge (implemented)

Create provider `normalized_json` without credentials. GET `/api/v1/data-sources/schema` returns the full versioned JSON Schema. POST `/{id}/ingest` accepts the schema object directly with optional Idempotency-Key. CLI tools must externally transform exports to this schema; this is **not native arbitrary Binance CLI execution**. No command is accepted or run by the server.

Minimal body:
```json
{"schema_version":1,"source_time":"2026-10-25T13:00:00Z","modules":[{"id":"spot","status":"ok"}],"balances":[{"module":"spot","asset":"USDT","balance":"10.00000001","net_equity":"10.00000001","available":"8","value_usdt":"10.00000001"}],"positions":[],"events":[]}
```

Amounts require finite decimal strings (not JSON numbers). Source time requires timezone and may not be more than five minutes in the future. Unknown/unprovided modules stay unknown; balances require explicit `ok` coverage. PM USD equity and derivative balances cannot be double counted. Events require stable external_id and kind and are deduplicated. Reusing an idempotency key for changed content returns 409. Observation order is monotonic; older snapshots return 409. Upload time does not make old observations fresh. Paused sources reject ingestion with 409; resume first. Inputs are capped at 2 MiB normalized JSON. Imported sources are never polled; interval defines freshness expectations only. Source deletion removes its events/receipts.

`tests/test_normalized_source.py` adds schema/provider, ingest/precision/dedup/idempotency conflict, invalid amount/command/future/PM validation, staleness and tenant coverage. After this addition the complete backend suite passed (480 tests). Router credential or binding changes clear prior snapshots and invalidate their sync receipts.

## Official references checked

- https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md (HMAC, timestamp, recvWindow, account/myTrades)
- https://raw.githubusercontent.com/binance/binance-api-swagger/master/spot_api.yaml (funding POST, Earn positions/rewards schemas)
- https://github.com/binance/binance-connector-python/tree/master/clients/derivatives_trading_portfolio_margin (official generated account API and accountEquity USD model)

The developers.binance.com site returned empty/unreachable content in this environment, so official GitHub raw sources were used instead.
