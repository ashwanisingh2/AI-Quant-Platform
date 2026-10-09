# Operator runbook

## Start safely

1. Create a unique private operator token and export `API_AUTH_TOKEN`.
2. Start one API process via `scripts/dev_api.sh`; it refuses missing/short/CI tokens.
3. Unlock the dashboard. Check Command center and the research/data mode.
4. Fetch mock data for initial tests. Confirm instrument, strategy, capital and mode.
5. Complete dry-run tests before considering a live route. Broker credentials are
   environment-only, distinct from the operator token.

Docker reads `.env`. Direct Python startup does not automatically load `.env`.
Never publish broker credentials, operator tokens or a populated `data/` directory.

## API clients

Use `Authorization: Bearer <private token>` for all routes except `/health`.
WebSocket `/ws/events` expects `{"token":"<private token>"}` within five seconds;
browser origins must be listed in `API_ALLOWED_ORIGINS`. Do not put tokens in URLs.
After authentication the socket sends `connection.ready`.

## Crash, timeout or expired broker token

- A failed trading loop stops and activates its risk veto. Inspect `/live/status`.
- Inspect the broker's order book, fills and positions directly, including pending orders.
- Compare them with Command center → Execution ledger / Order intent trail.
- `prepared` and `unknown` intents may already have executed. Do not blindly retry.
- Stop any active session. Record reconciliation only after checking every affected
  order/position, with a factual note. This unlocks the next live session.
- Renew broker credentials through the broker if needed, then restart the API.

## Emergency stop

Use the kill switch. Local decisions stop immediately; each cancellation and exit
is attempted independently. `squared_off` counts reported COMPLETE results only.
`incomplete` means manual action is required. Accepted/open exit orders are not
confirmed fills. Check the broker account even when the local result is successful.
Repeated kill requests return the previous result to avoid duplicate orders.

## Storage outage

New order submissions fail before side effects when the initial intent cannot be
persisted. A write failure after submission still requires manual broker checking.
Ensure adequate disk space. Back up the SQLite database using its online backup API
or stop the service before copying the database and WAL files together. Never delete
an unresolved journal merely to bypass the live-session gate.

## Release verification

Run regression/integration tests and dashboard build, verify network restrictions,
then perform broker-specific sandbox/account validation under operator control.
No automatic tests here send real orders. No profitability or unattended-live
certification is implied. Multi-process deployment and automated reconciliation
are outside this release.

## Daily data integrity and release gates

New API and CLI imports retain provider identity per candle. Legacy imports remain unknown; partially overwriting unknown or mock history never verifies the entire dataset. Provider-recorded is an origin label, not proof of accuracy or corporate-action adjustment. Radar excludes today's candles conservatively and flags history older than seven calendar days; this is not an exchange holiday calendar. Its data remains historical.

Parquet files use atomic replacement and a process-local writer lock. Run one API worker; multiple independent writers/processes are unsupported. File replacement prevents partial-file reads but is not a transactional multi-month commit. Back up only after stopping writers, and test restore in an isolated directory before relying on a backup.

Remaining release gates (not yet passed): licensed live feed and entitlement checks; authoritative F&O/sector master and exchange calendar; corporate-action adjustments; actual broker timeout, partial-fill and reconnect reconciliation; out-of-sample strategy validation; alert delivery and backup restore drills; deployment/TLS and load testing. Keep live execution disabled until those gates are independently verified. No code-only test establishes these external conditions.
