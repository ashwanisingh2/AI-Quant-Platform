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
cp .env.example .env                 # apni values daalo (default: live DISABLED)
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

**Dashboard pages:** 📊 Overview (P&L, positions, equity chart, **KILL SWITCH**, paper trading controls) · 🤖 Agent Console (AI signals + reasoning trace + approve/reject) · 🧠 Backtests (run + saved results) · 💾 Data (fetch + candlestick charts)

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
│   │   ├── kite_broker.py           # ✅ Phase 4 — Kite adapter (dry_run default, live gated)
│   │   └── live.py                  # ✅ Phase 4 — LiveTrader + price sources (replay/Kite)
│   ├── agent/          # ✅ Phase 2 — AI pipeline, LLM clients, registry, FastAPI + CLI
│   ├── api/            # ✅ Phase 3+4 — orchestration API (REST + WebSocket, live endpoints)
│   └── dashboard/      # ✅ Phase 3 — React + Vite (4 pages, live charts)
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
# Full test suite — Phase 0, 1, 2, 3, 4, 5 (46 tests)
# API/dashboard tests ke liye servers chalne chahiye (yeh auto-SKIP hote hain agar band hon)
python -m apps.api.main &          # port 8000
cd apps/dashboard && npm run dev & # port 5173
python scripts/test_all.py
```

Covers: data fetch/store/dedupe · backtests (stats + equity curve) · AI pipeline + risk veto · signal registry · paper trader (cash invariant) · kill switch · **risk engine (11 rules + audit trail)** · **strategy evaluator** · **Kite broker dry-run (fills, positions, square-off)** · **live trader dry-run + kill** · API endpoints · paper flow · **live API flow + safety gates + kill-switch** · dashboard proxy · **Phase 5: packaging (pyproject + entry points) · docker stack · .env safety · CI workflow · community files · demo script**.

## 🛡️ Phase 5 — OSS Release

- **📦 Packaging** — `pyproject.toml`: `pip install -e ".[all]"` → 4 CLI commands (`aiq-data`, `aiq-engine`, `aiq-agent`, `aiq-api`). Extras: `[llm]` (LiteLLM), `[kite]` (Kite Connect), `[dev]` (pytest, ruff, pyyaml).
- **🐳 Docker** — `Dockerfile` (API + CLIs) + `apps/dashboard/Dockerfile` (Vite → nginx) + `docker-compose.yml` (healthchecks, data volume, `.env` support). `docker compose up --build` → poora stack.
- **⚙️ CI** — `.github/workflows/ci.yml`: test suite (46 tests) + ruff lint + docker build — har push/PR pe.
- **🔒 Safety by default** — `.env.example` mein live trading **disabled** by default; `.env` git-ignored (secrets kabhi nahi).
- **🤝 Community** — [CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) · [SECURITY.md](SECURITY.md) (responsible disclosure — real money wala project) · issue/PR templates (PR template mein **safety checklist** hai).
- **📜 MIT License** — NautilusTrader (LGPL) library ki tarah use hota hai, explicitly allowed.

## 🗺️ Roadmap

- [x] **Phase 0** — Data foundation (fetch → store → query)
- [x] **Phase 1** — Backtest engine (NautilusTrader) + 2 classic strategies
- [x] **Phase 2** — AI agent service (signals with reasoning trace, human approval)
- [x] **Phase 3** — Dashboard (React) + orchestration API + paper trading
- [x] **Phase 4** — Risk engine hardening + live trading (Kite, gated, dry-run default)
- [x] **Phase 5** — OSS release (packaging, Docker, CI, community, docs) ← *abhi yahin hain*
- [ ] **Phase 6** — More brokers (Dhan/Upstox/Fyers), F&O, mobile app, hosted SaaS

## 📚 Design Docs

- [Exploration Doc](../ai-quant-platform-exploration.md) — idea, gap analysis, options
- [Architecture Doc](../ai-quant-architecture.md) — full system design, DB schema, API spec
- [Safety Doc](SAFETY.md) — live trading se pehle padhne zaroori
