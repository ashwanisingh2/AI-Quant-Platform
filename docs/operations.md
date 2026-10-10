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

## Personal Kotak Neo setup (paper and live)

Paper and live are separate paths. Paper never logs in to Kotak and never sends orders.

- **Paper:** `POST /paper/start` replays stored candles with simulated funds. `POST /live/start` with `mode: "dry_run"` and `broker: "kotak"` also replays stored candles and never calls Kotak. Fetch candles first with `POST /data/fetch`; at least 35 are needed.
- **Live:** `mode: "live"` plus `LIVE_TRADING_ENABLED=true`, the exact confirm phrase, a capital cap, and the four `KOTAK_*` variables. Pass the current 6-digit authenticator TOTP as `totp` in the request body. It is used once and never stored.

Kotak rules the adapter follows:

- Login is roughly once per trading day. Restart the live session each morning with a fresh TOTP.
- Orders are cash equity only (NSE/BSE, CNC or MIS) and are sent as LIMIT orders priced just through LTP (buffer 0.5%, rounded to tick). Market orders are never sent. F&O is rejected.
- Set `KOTAK_STATIC_IP` to the IP registered with Kotak. A mismatch refuses the session and logs out.
- Cancel requests are recorded as `CANCEL_REQUESTED`, not confirmed. Check the Kotak order book before treating a cancel as done.
- Each order carries an audit tag (`AIQ` + 12 hex characters, sent as the SDK `tag` and read back from `GuiOrdId`). Kotak adds its own Algo ID; the adapter does not send one.

### Kotak order outcomes

| Event | Adapter result | What the session does | Operator action |
|---|---|---|---|
| Kotak accepts the order | `OPEN` with Kotak order number | Journal records `OPEN` | Fill is not confirmed; check the order book |
| Kotak explicitly rejects it (`stat` not `Ok`) | `REJECTED` with `reason_code` (`stCode`) | Journal records `REJECTED`; trading continues | Read the reject reason in the Kotak app |
| SDK error, timeout or no order number | Exception | Journal records `unknown`; the loop stops with `trading_loop_failed` and the risk veto | Reconcile from the Kotak order book. No automatic retry |
| Session expired (`stCode` 403) | `KotakSessionExpired` | Loop stops (`error_type: KotakSessionExpired`) | Reconcile, then start a new live session with a fresh TOTP |
| More than 10 order or cancel requests per second on one exchange | `OrderRateLimitExceeded`, request not sent | Same as an SDK error: journal `unknown`, loop stops | The order never reached Kotak. Still confirm in the order book before recording reconciliation |

The 10 requests/second guard follows the SEBI retail API threshold. Placements and cancels both count, per exchange, and blocked attempts count too.

### Kotak and the kill switch

The kill switch cancels open orders and sends marketable LIMIT exits. With Kotak it will usually report `incomplete` with `manual_action_required: true`. This is expected:

- Cancels come back as `CANCEL_REQUESTED`, which is reported as `CancellationUnconfirmed`.
- LIMIT exits come back `OPEN`, which is reported as `FillUnconfirmed`. A `REJECTED` exit is reported as `ExitRejectedOrUnknown`.

Each exit is attempted on its own. One failure does not stop the remaining exits. After any kill, check every position and order in the Kotak app before recording reconciliation.

### Kotak SDK logs

The SDK (`kotakneoapi`) logs to stdout and to a rotating file, `logs/neo-api-client.log`, relative to the working directory. On a failed login it writes request bodies at ERROR level even with default settings. At `NEO_LOG_LEVEL=INFO` or `DEBUG` it writes every request and response, including session tokens. The SDK masks MPIN and TOTP only partially (`65***21`).

When live mode creates the SDK client, the adapter adds a redaction filter to the SDK handlers. The filter fully masks:

- MPIN, TOTP and the consumer key
- the session token, `sid` and `rid`
- PAN (`kId`) and account name
- mobile number and UCC

This includes values inside truncated response previews. Treat the filter as a safety net, not a guarantee:

- Keep `NEO_LOG_LEVEL` at `WARNING` (the default).
- In containers, set `NEO_LOG_FILE_ENABLED=false`, or keep `logs/` on private storage.
- `logs/` is ignored by git and excluded from Docker builds. Never attach these logs to issues.

Not verified against the live Kotak API. The adapter tests use a fake SDK client. Before any real order, check login, `limits`, `positions`, `order_report` and a quote with a read-only session. Then place one small order yourself, outside this repo's tests.
