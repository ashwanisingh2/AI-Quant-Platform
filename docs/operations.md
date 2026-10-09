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
