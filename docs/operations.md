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

## Single-host deployment without a public URL

This setup provides a private local dashboard at `http://localhost:5173`. A GitHub repository or merged PR does not itself create a running website. These Linux commands require Docker with Compose v2, Python 3 and permission to manage Docker:

```sh
python scripts/init_deployment.py
sudo install -d -o 10001 -g 10001 data
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 180
docker compose ps
```

The initializer creates `.env` with mode 0600 and will never overwrite it. Read the operator token from that file privately; do not paste it into chat, logs or source control. If `.env` already exists, retain it and configure `API_AUTH_TOKEN` manually. Existing data must be backed up before an administrator adjusts ownership to UID/GID 10001; the setup command does not recursively migrate existing files. API runs without root and with a read-only container filesystem; only `/app/data` and temporary storage are writable. Use exactly one API worker.

On a remote Linux host, keep loopback bindings and use SSH forwarding from your computer:

```sh
ssh -L 5173:127.0.0.1:5173 your-user@your-server
```

Then open `http://localhost:5173` on that computer. For public access, provision a host and HTTPS reverse proxy, configure exact `API_ALLOWED_ORIGINS`, and test WebSocket authentication through TLS before exposing the service. No hosting account, domain or public endpoint is provisioned by this repository.

`/health` is public process liveness. `/ready` requires operator authentication and returns 503 if authentication configuration, storage writes or SQLite integrity checks fail. Readiness does not certify data freshness, broker availability, unresolved trade reconciliation or profitability. Docker Compose checks `/ready` before starting the dashboard.

## Journal backup and restore drill

```sh
python scripts/backup_journal.py data/execution.sqlite3 /secure-backups/execution-unique.sqlite3
```

Choose a new destination each time. The utility uses SQLite's online backup API, applies mode 0600, checks integrity, and refuses overwrites. Store backups outside the web root. To verify recovery, open a copy at an isolated test path and confirm unresolved runs remain blocked. Automated regression tests cover this invariant. Full market-data backups and an off-host recovery drill are still operational responsibilities. Never restore a database over a running trading process or use an older backup to clear unknown order outcomes.
