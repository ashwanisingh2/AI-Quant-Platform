# Quant Platform V2

### An India-focused research and execution workspace.

[![CI](https://github.com/ashwanisingh2/AI-Quant-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/ashwanisingh2/AI-Quant-Platform/actions/workflows/ci.yml)
![Release](https://img.shields.io/badge/release-2.0.0a1-teal)
![Stage](https://img.shields.io/badge/stage-alpha%20%2F%20single%20operator-orange)

Research, backtesting, paper portfolios and broker execution in one workspace,
with shared strategy logic and a durable record of execution attempts.

**V2 is an alpha foundation, not a certified production trading system.**
Live routing defaults off. Real broker execution and profitability have not been
validated by the automated mock/dry-run suite.

[Quick start](#quick-start) · [Architecture](docs/architecture.md) · [Operations](docs/operations.md) · [Capability status](docs/capabilities.md) · [Contributing](CONTRIBUTING.md)

## What you can do

| Workspace | Working capability |
|---|---|
| Command center | Operating state, persistent sessions, order intents and recovery review |
| Research desk | Analyst → Trader → rules-based Risk, optional LLM, human approval |
| Strategy lab | Nautilus backtests, shared decision kernel, data fingerprint, benchmark and estimated costs |
| Paper portfolio | Replay stored candles with simulated funds |
| Execution | Kite, Dhan, Upstox, Fyers and Kotak Neo adapters; dry-run and gated live paths |
| Market data | Mock, bhavcopy and Kite providers; Parquet / DuckDB storage |
| Derivatives sandbox | Synthetic option chains, contract helpers and long-side strategy examples |

Broker adapter presence does not imply verified broker connectivity. Data-provider
availability and market-data rights must be established for your deployment.

## Quick start

Requirements: Python 3.12, Node 20+; Docker Compose is optional.

```bash
git clone https://github.com/ashwanisingh2/AI-Quant-Platform.git
cd AI-Quant-Platform
python -m venv .venv
. .venv/bin/activate
pip install -e '.[kite,dev]'
export API_AUTH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Keep this private token in a password manager to unlock the dashboard.
./scripts/dev_api.sh
```

In another terminal:

```bash
cd apps/dashboard
npm ci
npm run dev -- --host 127.0.0.1
```

Open `http://localhost:5173` and unlock with the same private operator token.
Use **Market data → mock → fetch** to create a sample dataset, then run a backtest
or dry-run session. Mock data is synthetic; it does not demonstrate strategy edge.

### Docker

Copy `.env.example` to `.env`, set a unique `API_AUTH_TOKEN` of at least 32
characters, then run `docker compose up --build`. Both published ports bind to
loopback by default. Keep `LIVE_TRADING_ENABLED` unset/false for research.

For a remote installation, terminate HTTPS/WSS at a trusted reverse proxy and
set explicit `API_ALLOWED_ORIGINS`. Run exactly **one API process** against the
execution database; multi-worker/HA operation is not supported.

## How execution is controlled

- Every HTTP endpoint except `/health` requires a bearer token; WebSocket access
  authenticates before event subscription. The browser stores the token in memory.
- Live mode requires environment enablement, the exact risk-confirmation phrase,
  a capital limit and configured broker credentials.
- API-managed sessions are stored in SQLite. An order intent is committed before
  submission, then the reported broker result is recorded. Timeouts become unknown
  outcomes, not automatic retries.
- Previous live sessions must be reconciled before another live session starts.
  The recovery screen records an **operator attestation**, not automatic broker verification.
- The kill switch stops local execution first. Failed, rejected or pending exits
  stay visible and require broker-account review. Repeated requests do not duplicate exits.

See the [operations runbook](docs/operations.md) before enabling any live route.

## Strategy consistency

EMA, RSI and the option-buyer wrapper use one `StrategyEvaluator` in Nautilus,
paper and live paths. A backtest saves decision traces and a hash of its bars.
This aligns decision rules, not fill outcomes. Daily bars, quote polling, different
warm-up windows and broker execution can still produce different trades.

Backtest gross returns are complemented by a configurable **post-fill turnover
cost estimate** and buy-and-hold comparison. This estimate is not an India tax
calculator, slippage simulation or out-of-sample validation. RSI now consistently
uses the shared 0–100 calculation; historical V1 results are not directly comparable.

## Repository map

```text
apps/api/                 Authenticated orchestration and operations API
apps/dashboard/           React workspace and recovery review
apps/agent/               Research pipeline, LLM clients and approval registry
apps/engine/strategies/    Shared decision kernel and Nautilus adapters
apps/engine/brokers/       Broker adapter boundary
libs/risk/                Pre-trade rules
libs/storage/             Market data store and SQLite execution journal
docs/                     Architecture, capabilities and operations
scripts/                  Regression tests and development launcher
```

## Validation

```bash
pip install httpx
python -m unittest scripts.test_auth scripts.test_failure_handling scripts.test_v2
ruff check .
npm ci --prefix apps/dashboard
npm run build --prefix apps/dashboard
python scripts/test_all.py
```

The full integration suite needs the API/dashboard running with the same
`API_AUTH_TOKEN`; CI starts both and seeds deterministic fixtures. CI also builds
Docker images. Unit tests use fake brokers and cannot validate live exchange fills.

## Open-source approach

NautilusTrader is an actual dependency. The other projects discussed for V2 are
architecture/research references, not silently bundled integrations. See the
[capability and upstream matrix](docs/capabilities.md). Upstream code reuse must
be evaluated against the license of the exact version and files involved.

Project code: [MIT](LICENSE). Report vulnerabilities via the process in
[SECURITY.md](SECURITY.md). Historical V1 documentation is in
[docs/legacy-guide.md](docs/legacy-guide.md).
