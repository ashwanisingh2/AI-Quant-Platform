# 🤖 AI Quant Platform

**India-first, AI-native, open-source trading platform.**

AI agents se signals + production-grade execution + fast backtesting + dashboard — ek hi jagah.
India-first: Zerodha Kite / Dhan / Upstox se live trading.

> ⚠️ **Disclaimer:** Educational & personal use ke liye. Real money se pehle kam se kam 2-3 mahine paper trading. Ye financial advice nahi hai.

---

## 🚀 Quickstart

```bash
# Option A — pip se poora package (4 CLI commands milte hain: aiq-data, aiq-engine, aiq-agent, aiq-api)
pip install -e ".[all]"              # all = llm + kite extras

# Option B — requirements se
pip install -r requirements.txt

python scripts/demo_phase0.py        # Phase 0: data pipeline demo
python scripts/demo_phase1.py        # Phase 1: backtest engine demo
python scripts/demo_phase2.py        # Phase 2: AI agent pipeline demo
python scripts/demo_phase4.py        # Phase 4: risk engine + live dry-run demo (100% safe)
```

## 🐳 Docker — Poora Stack Ek Command Mein

```bash
cp .env.example .env                 # set API_AUTH_TOKEN; live defaults DISABLED
docker compose up --build

# Dashboard → http://localhost:5173   ·   API → http://localhost:8000
```

Compose mein 2 services hain: `api` (Python, healthcheck ke saath) + `dashboard` (Vite build → nginx, `/api` aur `/ws` proxy karta hai). Data `./data` volume pe persist hota hai.

## 🖥️ Run the Full System (Phase 3 + 4)

```bash
# Terminal 1 — Orchestration API (port 8000)
python -m apps.api.main

# Terminal 2 — Dashboard (port 5173)
cd apps/dashboard && npm install && npm run dev

# Browser → http://localhost:5173
```

**Dashboard pages:** 📊 Overview (P&L, positions, equity chart, **KILL SWITCH**, paper trading controls) · 🟢 **Live** (multi-broker live/dry-run trading, positions, orders, kill switch) · 📈 **FnO** (option chain — strikes, CE/PE premiums, ITM/ATM/OTM, contract data fetch) · 🤖 Agent Console (AI signals + reasoning trace + approve/reject) · 🧠 Backtests (run + saved results) · 💾 Data (fetch + candlestick charts)

## 🧩 CLIs

```bash
# Data (Phase 0)
python -m apps.data_gateway.main fetch --provider bhavcopy --symbol RELIANCE --days 30   # REAL NSE, no key
python -m apps.data_gateway.main list / show --instrument NSE:RELIANCE --spark

# Backtests (Phase 1)
python -m apps.engine.main strategies
python -m apps.engine.main backtest --instrument NSE:TESTCO --strategy ema_cross --set fast_ema=5

# Paper trading (Phase 3, headless)
python -m apps.engine.main paper --instrument NSE:TESTCO --strategy ema_cross --speed 0

# Live trading (Phase 4 — dry-run by default, real sirf gates ke saath)
python -m apps.engine.main live --instrument NSE:TESTCO --strategy ema_cross --mode dry_run --speed 0

# AI Agent (Phase 2)
python -m apps.agent.main analyze --instrument NSE:TESTCO --llm mock
python -m apps.agent.main serve --port 8001
```

## 🤖 Real LLM (optional)

```bash
pip install litellm
export LLM_MODEL="gemini/gemini-2.0-flash"
export LLM_API_KEY="..."
python -m apps.agent.main analyze --instrument NSE:RELIANCE --llm auto
```

## 🔄 The Full Loop (kaise kaam karta hai)

```
1. DATA      → bhavcopy (real NSE, no key) / kite / mock → Parquet
2. BACKTEST  → NautilusTrader engine → returns, Sharpe, drawdown, equity curve
3. AI SIGNAL → Analyst → Trader → Risk pipeline → signal + reasoning trace
4. APPROVE   → human (dashboard Agent Console) → approved
5. PAPER     → real prices (replay/live), fake money → orders, positions, P&L live
6. DRY-RUN   → live prices + simulated broker → bina paisa lagaye live jaisa (Phase 4)
7. LIVE      → Zerodha Kite → REAL MONEY — 4 safety gates + risk engine + kill switch
8. KILL      → ek button → sab band, open orders cancel, saari positions square off
```

## 🛡️ Phase 4 — Risk Engine + Live Trading (Kite)

### Risk Engine (`libs/risk/engine.py`) — har order iske bina broker nahi pahunch sakta

11 pre-trade checks, har check ka audit trail:

1. **Kill switch** — active → sab reject
2. **Trading hours** — IST Mon–Fri 09:15–15:30 only
3. **Instrument whitelist** — sirf allowed instruments
4. **Strategy whitelist** — sirf allowed strategies
5. **Price deviation** — reference se ≤10% (circuit sanity)
6. **Position value cap** — max 20% of capital per instrument + ₹2L absolute
7. **Max open positions** — 5
8. **Daily loss limit** — din mein −3% → band for the day
9. **Max drawdown** — −10% → kill territory
10. **Min AI confidence** — 0.6 se kam → reject
11. **Order rate limit** — 5 orders/min

### Live Trading — 4 safety gates (real money se pehle)

| Gate | Kaise enable |
|---|---|
| 1. Env var | `LIVE_TRADING_ENABLED=true` |
| 2. Confirm phrase | `"I UNDERSTAND THIS TRADES REAL MONEY"` (exact) |
| 3. Max capital | `LIVE_MAX_CAPITAL` (default ₹50,000) se zyada nahi |
| 4. Kite creds | `KITE_API_KEY` + `KITE_ACCESS_TOKEN` |

- **Default product: CNC** (delivery — no leverage, no intraday risk)
- **dry_run default hai** — real prices + simulated broker, bina paisa lagaye
- **Kill switch** (`POST /kill-switch`) → paper + live dono band, open orders cancel, saari positions square off
- Live start hone pe broker ke real positions/orders **reconcile** hote hain (startup sync)
- Poori checklist: [`SAFETY.md`](SAFETY.md)

### Live API endpoints

```bash
# Dry-run live (replay prices, simulated orders — safe)
curl -X POST localhost:8000/live/start -H 'Content-Type: application/json' \
  -d '{"instrument":"NSE:TESTCO","strategy":"ema_cross","mode":"dry_run","capital":1000000}'

curl localhost:8000/live/status     # running, positions, orders, equity curve
curl -X POST localhost:8000/live/stop
curl -X POST localhost:8000/kill-switch   # sab kuch band + square off
```

## 📁 Project Structure

```
ai-quant-platform/
├── apps/
│   ├── data_gateway/   # ✅ Phase 0 — providers (mock|bhavcopy|kite), CLI
│   ├── engine/         # ✅ Phase 1 — Nautilus backtests, strategies, CLI
│   │   ├── paper.py    # ✅ Phase 3 — paper trader (replay/live, kill switch)
│   │   ├── strategies/evaluator.py  # ✅ Phase 4 — shared strategy logic (paper + live)
│   │   ├── kite_broker.py           # ✅ Phase 6 — compat shim (neeche dekho)
│   │   ├── brokers/                 # ✅ Phase 6+7 — base + kite + dhan + upstox + fyers + factory
│   │   └── live.py                  # ✅ Phase 4 — LiveTrader + price sources (replay/Kite/Dhan)
│   ├── agent/          # ✅ Phase 2 — AI pipeline, LLM clients, registry, FastAPI + CLI
│   ├── api/            # ✅ Phase 3+4+6 — orchestration API (REST + WebSocket, live + brokers)
│   └── dashboard/      # ✅ Phase 3+6+8 — React + Vite (6 pages, live charts, Live + FnO chain pages)
├── libs/
│   ├── shared/         # models (Candle, Signal, AgentRun...) + charts
│   ├── storage/        # Parquet + DuckDB store
│   ├── risk/engine.py  # ✅ Phase 4 — 11-check pre-trade risk engine + audit trail
│   └── prompts/v1/     # versioned agent prompts
├── scripts/            # demo_phase0/1/2/4.py + test_all.py (full suite, 46 tests)
├── pyproject.toml      # ✅ Phase 5 — packaging + 4 CLI entry points (aiq-*)
├── Dockerfile          # ✅ Phase 5 — API + CLIs image
├── docker-compose.yml  # ✅ Phase 5 — api + dashboard, ek command mein
├── .github/            # ✅ Phase 5 — CI workflow + issue/PR templates
├── SAFETY.md           # ✅ Phase 4 — live trading se pehle ki checklist
├── SECURITY.md         # ✅ Phase 5 — responsible disclosure
├── CONTRIBUTING.md     # ✅ Phase 5 — kaise contribute karein
├── LICENSE             # ✅ Phase 5 — MIT
└── data/               # ohlcv/ backtests/ agent_runs/ (git-ignored)
```

## 🤝 Community

- **Contribute:** [CONTRIBUTING.md](CONTRIBUTING.md) — bugs, strategies, prompts, brokers, dashboard — sab welcome!
- **Security:** [SECURITY.md](SECURITY.md) — vulnerability? Public issue mat banao, responsible disclosure karo.
- **Code of Conduct:** [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- **License:** [MIT](LICENSE)

## 🧪 Testing

```bash
# Full test suite — Phase 0, 1, 2, 3, 4, 5, 6, 7, 8 (78 tests)
# API/dashboard tests ke liye servers chalne chahiye (yeh auto-SKIP hote hain agar band hon)
python -m apps.api.main &          # port 8000
cd apps/dashboard && npm run dev & # port 5173
python scripts/test_all.py
```

Covers: data fetch/store/dedupe · backtests (stats + equity curve) · AI pipeline + risk veto · signal registry · paper trader (cash invariant) · kill switch · **risk engine (11 rules + audit trail)** · **strategy evaluator** · **Kite broker dry-run (fills, positions, square-off)** · **live trader dry-run + kill** · API endpoints · paper flow · **live API flow + safety gates + kill-switch** · dashboard proxy · **Phase 5: packaging (pyproject + entry points) · docker stack · .env safety · CI workflow · community files · demo script** · **Phase 6: broker base conformance + factory · Dhan dry-run · Dhan live trader · /brokers API · live broker selection + gates · CLI --broker · dashboard production build**.

## 🛡️ Phase 5 — OSS Release

- **📦 Packaging** — `pyproject.toml`: `pip install -e ".[all]"` → 4 CLI commands (`aiq-data`, `aiq-engine`, `aiq-agent`, `aiq-api`). Extras: `[llm]` (LiteLLM), `[kite]` (Kite Connect), `[dev]` (pytest, ruff, pyyaml).
- **🐳 Docker** — `Dockerfile` (API + CLIs) + `apps/dashboard/Dockerfile` (Vite → nginx) + `docker-compose.yml` (healthchecks, data volume, `.env` support). `docker compose up --build` → poora stack.
- **⚙️ CI** — `.github/workflows/ci.yml`: test suite (46 tests) + ruff lint + docker build — har push/PR pe.
- **🔒 Safety by default** — `.env.example` mein live trading **disabled** by default; `.env` git-ignored (secrets kabhi nahi).
- **🤝 Community** — [CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) · [SECURITY.md](SECURITY.md) (responsible disclosure — real money wala project) · issue/PR templates (PR template mein **safety checklist** hai).
- **📜 MIT License** — NautilusTrader (LGPL) library ki tarah use hota hai, explicitly allowed.

## 🏭 Phase 6 — Multi-Broker + Live Dashboard

**Broker abstraction** (`apps/engine/brokers/`) — vnpy/ccxt wali multi-broker architecture. Ek `BrokerBase` interface, registry + factory se naya broker add karna = ek file:

```
apps/engine/brokers/
├── base.py          # BrokerBase — same interface for all (connect, orders, positions, square_off...)
├── kite_broker.py   # Zerodha (registry: "kite")
└── dhan_broker.py   # Dhan (registry: "dhan") — security_id, NSE_EQ, CNC/INTRA mapping
```

- **Dhan support** — official `dhanhq` library (lazy import, `pip install .[dhan]`). Dry-run default, live gated (same 4 gates + `DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN`). Dhan ki alag baatein handle ki gayi hain: security_id (string), `NSE_EQ` segments, `CNC`/`INTRA` products, `TRADED` status.
- **Live Dashboard page** 🟢 — broker selector (creds dikhata hai), dry_run/live mode (live disabled until gates), instrument/strategy/capital, **confirm phrase box for live mode**, equity chart, positions, open orders, kill switch.
- **API** — `GET /brokers` (available brokers + creds status) · `POST /live/start` ab `broker: "kite" | "dhan"` leta hai.
- **CLI** — `aiq-engine live --broker dhan --mode dry_run ...`
- **Aage ke brokers** (Upstox/Fyers) ke liye bas ek file + `@register_broker` — roadmap mein Phase 7.

```bash
# Dhan dry-run (bina paisa lagaye)
python -m apps.engine.main live --instrument NSE:TESTCO --broker dhan --mode dry_run

# API se brokers dekhna
curl localhost:8000/brokers
```

## 🏭 Phase 7 — 4 Brokers: Kite + Dhan + Upstox + Fyers

Registry pattern ne prove kar diya: **naya broker = ek file + `@register_broker`**. Phase 7 mein 2 aur brokers aaye:

| Broker | Registry name | SDK (extra) | Credentials | Alag baatein |
|---|---|---|---|---|
| Zerodha | `kite` | `.[kite]` (kiteconnect) | `KITE_API_KEY` + token | int instrument token |
| Dhan | `dhan` | `.[dhan]` (dhanhq) | `DHAN_CLIENT_ID` + token | security_id string, `NSE_EQ`, CNC/INTRA |
| **Upstox** 🆕 | `upstox` | `.[upstox]` (upstox-python-sdk) | `UPSTOX_ACCESS_TOKEN` | `NSE_EQ\|ISIN` key, products D/I, lowercase status |
| **Fyers** 🆕 | `fyers` | `.[fyers]` (fyers-apiv3) | `FYERS_CLIENT_ID` + token | `NSE:SBIN-EQ` symbol, side/type numbers, int status codes |

- **Sab brokers same interface** — `BrokerBase`. LiveTrader, risk engine, kill switch, dashboard — sab bina badle kaam karte hain.
- **Dashboard automatic** — Live page `/brokers` se dynamic fetch karta hai; naye brokers bina UI change ke dikh gaye.
- **Same safety sab par** — 4 gates, risk engine ke 11 checks, kill switch — har broker pe.
- **CLI/API** — `--broker upstox|fyers`, `/live/start {"broker": "fyers"}`.

```bash
# Kisi bhi broker pe dry-run
python -m apps.engine.main live --instrument NSE:TESTCO --broker fyers --mode dry_run
curl localhost:8000/brokers    # → 4 brokers, creds status ke saath
```

## ⚠️ Phase 8 — F&O (Futures & Options) Support

> ⚠️ **F&O = leverage = high risk.** Neeche wali safety rules hamesha lagti hain.

**Symbol format (canonical):**
```
NSE:NIFTY-23OCT25-FUT          # future
NSE:NIFTY-23OCT25-24000-CE     # call option
NSE:NIFTY-23OCT25-24000-PE     # put option
```

**Kya mila:**
- **`libs/shared/fno.py`** — symbol parse/format, lot sizes (NIFTY 75, BANKNIFTY 35, FINNIFTY 65...), `atm_strike`, monthly expiry (last Thursday), compact broker format (`NIFTY25OCTFUT`)
- **Risk engine +3 F&O checks** — `fno_lot_size` (qty lot ka multiple) · `fno_notional_cap` (default 100% of capital) · `no_naked_option_sell` (**MVP mein naked option selling nahi** — sirf buy/long-exit). Equity position cap F&O pe nahi lagta (apna notional cap hai).
- **All 4 brokers** — F&O symbol mapping per broker (Kite/Upstox: `NFO:NIFTY25OCTFUT` · Dhan: `NSE_FNO` segment + security_id · Fyers: `NSE:NIFTY25OCTFUT`)
- **Mock F&O data** — synthetic futures/options candles + `get_option_chain()` (21 strikes, CE/PE premiums)
- **Option Chain har jagah dikhta hai** 🆕 — dashboard pe naya **📈 FnO tab** (strike table: CE/PE premiums, ITM/ATM/OTM, per-contract Fetch button) · API `GET /fno/chain?underlying=NIFTY&spot=24000` + `/fno/underlyings` · CLI `aiq-data chain --symbol NIFTY`
- **`atm_call_buy` strategy** — options BUY only (EMA cross on premium, long exit). Naked selling nahi karti.
- **Nautilus instruments** — `FuturesContract`/`OptionContract` with real lot sizes (backtest = signal validation; CASH account full notional debit karta hai, toh capital ≥ 1 lot notional rakho — NIFTY ≈ ₹18L at 24000)

```bash
# F&O data fetch + backtest (mock se synthetic data)
python -m apps.data_gateway.main fetch --provider mock --symbol NIFTY-23OCT25-FUT --days 90
python -m apps.engine.main backtest --instrument NSE:NIFTY-23OCT25-FUT --strategy ema_cross --capital 5000000

# Option chain dekho — CLI se
python -m apps.data_gateway.main chain --symbol NIFTY

# Option chain dekho — API se (dashboard isse use karta hai)
curl "localhost:8000/fno/chain?underlying=NIFTY&spot=24000"

# F&O paper/live dry-run (lot size enforce hoga)
python -m apps.engine.main live --instrument NSE:NIFTY-23OCT25-FUT --strategy ema_cross --mode dry_run
```

## 🗺️ Roadmap

- [x] **Phase 0** — Data foundation (fetch → store → query)
- [x] **Phase 1** — Backtest engine (NautilusTrader) + 2 classic strategies
- [x] **Phase 2** — AI agent service (signals with reasoning trace, human approval)
- [x] **Phase 3** — Dashboard (React) + orchestration API + paper trading
- [x] **Phase 4** — Risk engine hardening + live trading (Kite, gated, dry-run default)
- [x] **Phase 5** — OSS release (packaging, Docker, CI, community, docs)
- [x] **Phase 6** — Multi-broker abstraction + Dhan + Live dashboard
- [x] **Phase 7** — 4 brokers: Kite + Dhan + Upstox + Fyers
- [x] **Phase 8** — F&O support (symbols, lots, risk checks, options-buyer strategy, option chain UI) ← *abhi yahin hain*
- [ ] **Phase 9** — Mobile app, hosted SaaS, margin-based F&O accounting

## 📚 Design Docs

- [Exploration Doc](../ai-quant-platform-exploration.md) — idea, gap analysis, options
- [Architecture Doc](../ai-quant-architecture.md) — full system design, DB schema, API spec
- [Safety Doc](SAFETY.md) — live trading se pehle padhne zaroori

## Operator authentication

Generate a unique token with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
and set `API_AUTH_TOKEN` in `.env` (at least 32 characters). Docker Compose reads this
file; for direct Python/CLI startup, export the variables in your shell first.
Open the dashboard and enter this token to unlock it. Reloading the page or locking
clears the dashboard token; it is kept in memory, never localStorage or a URL.

All HTTP routes except `/health`, including API docs, require
`Authorization: Bearer <API_AUTH_TOKEN>`. WebSockets require an initial JSON
message `{"token":"<API_AUTH_TOKEN>"}` within five seconds; no events are sent
before authentication. Browser WebSocket origins must match `API_ALLOWED_ORIGINS`.
Missing or short server tokens deny access; there is no anonymous fallback.

This is a **single-operator** model: the token grants all platform permissions.
It does not provide multi-user accounts, roles, or broker OAuth callbacks. Use a
trusted HTTPS reverse proxy for remote access (including WSS), set explicit origins,
and keep the backend private. Compose publishes both ports on loopback by default.
Never send a token over a remote HTTP connection.

To rotate the operator token, replace it and restart the backend; existing sockets
close on restart. Broker tokens are separate: obtain/renew them through the broker,
update the environment, restart, and verify connection before live trading. Automatic
broker token refresh is not implemented. `/brokers` reports credential presence,
not whether the broker accepted the token. Dhan/Fyers startup rejects error responses.

### Development startup and failure handling

`scripts/dev_api.sh` requires an exported, private `API_AUTH_TOKEN` of at least
32 characters. It preserves that value, rejects CI tokens, never prints the token,
and binds the API to `127.0.0.1`. Generate a token as described above; the script
never reads credentials from the CI workflow.

The kill switch stops local trading first and attempts cancellations and exits
independently. Its response includes `cancelled_orders`, `exit_orders_submitted`,
`squared_off` (confirmed COMPLETE responses only), and structured `errors`.
`status: incomplete` / `manual_action_required: true` means the broker actions
failed or were not confirmed. Inspect the broker account immediately; an accepted
market order is not a confirmed fill. Repeated kill requests return the stored
result to avoid duplicate exits; perform further recovery directly with the broker.

Unexpected trading-loop failures stop the loop, activate the risk veto and emit
`live.error`. `/live/status` retains the error even when portfolio reads fail.
There is no automatic order retry or restart: reconcile broker orders/positions
before starting again. Process restarts do not preserve these in-memory reports.
