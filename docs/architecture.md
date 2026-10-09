# V2 architecture

## Decision 1: one decision kernel

`StrategyEvaluator.on_price(price, held_qty)` owns EMA/RSI signal decisions.
Nautilus `SharedStrategy`, `PaperTrader` and `LiveTrader` call this contract.
The adapter supplies actual holdings and handles order execution. Signal traces
allow replay comparisons on identical bars and held quantities.

This is not backtest/live fill parity: cadence, spreads, slippage, rejected orders,
market hours and partial fills remain separate concerns. Quote polling is not a
bar aggregator. Daily-bar research must not be treated as validated intraday logic.

## Decision 2: broker is the authority for account state

SQLite is a durable local record of attempts, not an exchange settlement ledger.
`prepared` is persisted before broker submission; an exception records `unknown`.
A crash between submission and persistence can leave `prepared` despite a broker
fill. Never automatically resubmit such an intent.

## Decision 3: conservative recovery admission

Only one unresolved live session is admitted by a SQLite transaction. All previous
live sessions, including clean local stops, require operator reconciliation before
a new live run. The UI explicitly distinguishes this attestation from a broker query.

Run state: starting → running → stopped / recovery_required / startup_failed →
reconciled. Run status and broker order status are different concepts. No automatic
startup resume, distributed lock or multi-process account coordination is provided.

## Decision 4: single operator deployment

Bearer authentication grants full operator access. API, SQLite and broker client
state live in one process. HTTPS is provided by the deployment proxy. The API does
not implement user roles, multi-tenancy or automatic broker OAuth renewal.

## Persistence and observability

API-managed sessions and broker-order submissions use `data/execution.sqlite3`
(or `EXECUTION_DB`). WAL transactions use FULL synchronization. Market bars remain
in Parquet; research and backtest reports are JSON. Do not store credentials or raw
SDK exceptions in the journal. Operator reconciliation notes must not contain secrets.

CLI-only sessions do not yet use the durable API execution journal. Use the API
workflow when you need durable session admission and reconciliation controls.
