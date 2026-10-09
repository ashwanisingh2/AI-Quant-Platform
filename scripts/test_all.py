"""Full test suite — Phase 0, 1, 2, 3, 4, 5, 6.

Run:  python scripts/test_all.py

Phase 3 ke API/dashboard tests ke liye servers chalne chahiye:
  python -m apps.api.main          (port 8000)
  cd apps/dashboard && npm run dev (port 5173)
Agar server nahi chal raha toh woh tests SKIP ho jayenge.
"""
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

API = "http://localhost:8000"
DASH = "http://localhost:5173"

results: list[tuple[str, bool, str]] = []


def check(name: str, fn):
    try:
        fn()
        results.append((name, True, ""))
        print(f"  ✅ {name}")
    except Exception as e:
        results.append((name, False, str(e)))
        print(f"  ❌ {name} — {type(e).__name__}: {e}")


def skip(name: str, why: str):
    results.append((name, None, why))
    print(f"  ⏭️  {name} — SKIP ({why})")


# ============================================================
print("\n📦 PHASE 0 — Data Foundation")
# ============================================================

def t_p0_fetch_store_query():
    from apps.data_gateway.providers.mock_provider import MockProvider
    from libs.storage.parquet_store import ParquetStore
    store = ParquetStore()
    candles = MockProvider().get_historical("TESTALL", days=40)
    assert len(candles) == 40, f"expected 40, got {len(candles)}"
    store.write_candles(candles)
    back = store.read_candles("NSE:TESTALL")
    assert len(back) == 40, f"read back {len(back)}"
    s = store.summary("NSE:TESTALL")
    assert s["candles"] == 40 and s["last_close"] > 0


def t_p0_incremental_dedupe():
    """Same data dobara fetch → duplicate nahi hona chahiye."""
    from apps.data_gateway.providers.mock_provider import MockProvider
    from libs.storage.parquet_store import ParquetStore
    store = ParquetStore()
    candles = MockProvider().get_historical("TESTALL", days=40)
    store.write_candles(candles)  # dobara
    store.write_candles(candles)  # aur ek baar
    back = store.read_candles("NSE:TESTALL")
    assert len(back) == 40, f"dedupe fail: {len(back)} candles (expected 40)"


def t_p0_cli():
    r = subprocess.run([sys.executable, "-m", "apps.data_gateway.main", "list"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "NSE:" in r.stdout, "instruments list empty"


check("fetch → store → query (mock data)", t_p0_fetch_store_query)
check("incremental fetch dedupe (no duplicates)", t_p0_incremental_dedupe)
check("data_gateway CLI (list)", t_p0_cli)

# ============================================================
print("\n🧠 PHASE 1 — Backtest Engine")
# ============================================================

def t_p1_backtest_ema():
    from apps.engine.runner import run_backtest
    r = run_backtest("NSE:TESTCO", "ema_cross", {}, None, None, 500_000)
    assert r["days"] > 0, "0 days"
    assert len(r["equity_curve"]) == r["days"], "equity curve mismatch"
    assert "total_return_pct" in r and "max_drawdown_pct" in r
    assert r["max_drawdown_pct"] <= 0, "drawdown should be ≤ 0"


def t_p1_backtest_rsi_params():
    from apps.engine.runner import run_backtest
    r = run_backtest("NSE:INFY", "rsi",
                     {"period": 14, "oversold": 35, "overbought": 65}, None, None, 500_000)
    assert r["strategy"] == "rsi"
    assert r["params"]["oversold"] == 35, "params not applied"


def t_p1_cli():
    r = subprocess.run([sys.executable, "-m", "apps.engine.main", "strategies"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "ema_cross" in r.stdout and "rsi" in r.stdout


check("backtest ema_cross (stats + equity curve)", t_p1_backtest_ema)
check("backtest rsi (custom params)", t_p1_backtest_rsi_params)
check("engine CLI (strategies)", t_p1_cli)

# ============================================================
print("\n🤖 PHASE 2 — AI Agent")
# ============================================================

def t_p2_snapshot():
    from apps.agent.analysis import build_snapshot
    from libs.storage.parquet_store import ParquetStore
    candles = ParquetStore().read_candles("NSE:TESTCO")
    snap = build_snapshot("NSE:TESTCO", candles)
    assert snap.current_price > 0
    assert snap.rsi_14 is not None and 0 <= snap.rsi_14 <= 100
    assert snap.trend in ("up", "down", "sideways")


def t_p2_pipeline():
    from apps.agent.analysis import build_snapshot
    from apps.agent.graph.pipeline import run_pipeline
    from apps.agent.llm.mock_llm import MockLLMClient
    from libs.shared.models import PortfolioState
    from libs.storage.parquet_store import ParquetStore
    candles = ParquetStore().read_candles("NSE:TESTCO")
    snap = build_snapshot("NSE:TESTCO", candles)
    run = run_pipeline(snap, PortfolioState(cash=1_000_000, total_value=1_000_000),
                       "test", {}, MockLLMClient())
    assert len(run.steps) == 3, f"expected 3 steps, got {len(run.steps)}"
    assert [s.agent for s in run.steps] == ["analyst", "trader", "risk"]
    assert run.final_signal.direction.value in ("BUY", "SELL", "HOLD")
    assert run.risk_decision["decision"] in ("approve", "adjust", "veto")
    assert run.total_tokens > 0 and run.total_cost_inr > 0


def t_p2_risk_veto():
    """Low confidence signal → risk veto hona chahiye."""
    from apps.agent.graph.pipeline import risk_check
    from libs.shared.models import MarketSnapshot, PortfolioState, Signal, SignalDirection
    sig = Signal(instrument="NSE:X", direction=SignalDirection.BUY, confidence=0.3)
    snap = MarketSnapshot(instrument="NSE:X", timestamp=datetime.now(),
                          current_price=100.0, window_high=110.0, window_low=90.0)
    d = risk_check(sig, snap, PortfolioState(cash=1_000_000, total_value=1_000_000), {})
    assert d["decision"] == "veto", f"expected veto, got {d['decision']}"


def t_p2_registry():
    from apps.agent.registry import SignalRegistry
    from libs.shared.models import AgentRun, AgentStep, Signal, SignalDirection
    with tempfile.TemporaryDirectory() as td:
        run = AgentRun(
            id="test1", instrument="NSE:X", strategy="s",
            steps=[AgentStep(agent="analyst", model="m", output="o",
                             tokens=1, cost_inr=0.1, duration_ms=1)],
            final_signal=Signal(instrument="NSE:X", direction=SignalDirection.BUY, confidence=0.8),
            risk_decision={"decision": "approve"}, risk_explanation="ok",
            total_tokens=1, total_cost_inr=0.1, duration_ms=1, llm_provider="mock",
        )
        (Path(td) / "test1.json").write_text(run.model_dump_json())
        reg = SignalRegistry(Path(td))
        assert reg.get("test1") is not None, "run load nahi hui"
        reg.approve("test1")
        assert reg.get("test1")["final_signal"]["status"] == "approved"
        appr = reg.approved("NSE:X")
        assert len(appr) == 1 and appr[0]["run_id"] == "test1"
        assert reg.approved("NSE:OTHER") == [], "instrument filter fail"


check("market snapshot (indicators)", t_p2_snapshot)
check("agent pipeline (analyst→trader→risk)", t_p2_pipeline)
check("risk rules (low confidence → veto)", t_p2_risk_veto)
check("signal registry (approve + filter)", t_p2_registry)

# ============================================================
print("\n💰 PHASE 3 — Paper Trading (headless)")
# ============================================================

def t_p3_paper_headless():
    import asyncio

    from apps.engine.paper import PaperTrader

    async def run():
        events = []
        trader = PaperTrader("NSE:TESTCO", "ema_cross", {"quantity": 50},
                             capital=500_000, speed=0,
                             on_event=lambda e: events.append(e), limit=60)
        await trader.start()
        await trader._task
        return trader, events

    trader, events = asyncio.run(run())
    s = trader.state()
    assert s["n_orders"] == len(s["orders"]), "order count mismatch"
    assert len(s["equity_curve"]) > 0, "no equity curve"
    # 💰 cash invariant: capital - buys + sells == final cash
    cash = 500_000.0
    for o in s["orders"]:
        if o["side"] == "BUY":
            cash -= o["qty"] * o["price"]
        else:
            cash += o["qty"] * o["price"]
    assert abs(cash - s["cash"]) < 0.01, f"cash invariant broken: {cash} vs {s['cash']}"
    # event stream sanity
    types = {e["type"] for e in events}
    assert "paper.tick" in types, "no ticks emitted"


def t_p3_paper_kill():
    import asyncio

    from apps.engine.paper import PaperTrader

    async def run():
        trader = PaperTrader("NSE:TESTCO", "ema_cross", {},
                             capital=500_000, speed=0.05, limit=120)
        await trader.start()
        await asyncio.sleep(1.0)  # thoda trade hone do
        trader.kill()
        await asyncio.sleep(0.3)
        return trader.state()

    s = asyncio.run(run())
    assert s["killed"] is True, "not killed"
    assert s["running"] is False, "still running"
    assert all(p["qty"] == 0 for p in s["positions"]), "positions not closed"


check("paper trader headless (cash invariant)", t_p3_paper_headless)
check("paper trader kill switch (positions close)", t_p3_paper_kill)

# ============================================================
print("\n🛡️ PHASE 4 — Risk Engine + Kite Live Trading")
# ============================================================

def _risk_ctx(**kw):
    from datetime import datetime, timedelta, timezone

    from libs.risk.engine import RiskContext
    IST = timezone(timedelta(hours=5, minutes=30))
    base = dict(capital=1_000_000, cash=1_000_000, positions_value=0.0,
                open_positions=0, daily_pnl_pct=0.0, current_drawdown_pct=0.0,
                reference_price=1000.0, instrument="NSE:TESTCO",
                now=datetime(2026, 10, 12, 10, 0, tzinfo=IST))  # Monday 10:00 IST
    base.update(kw)
    return RiskContext(**base)


def _risk_engine(**limits):
    from libs.risk.engine import RiskEngine, RiskLimits
    limits.setdefault("trading_hours_only", False)  # rules isolate karne ke liye
    return RiskEngine(RiskLimits(**limits))


def t_p4_risk_kill_switch():
    eng = _risk_engine()
    assert eng.check_order("BUY", 100, 1000.0, _risk_ctx()).allowed
    eng.kill()
    d = eng.check_order("BUY", 100, 1000.0, _risk_ctx())
    assert not d.allowed and "kill" in d.reason.lower(), d.reason
    eng.reset_kill()
    assert eng.check_order("BUY", 100, 1000.0, _risk_ctx()).allowed


def t_p4_risk_trading_hours():
    from datetime import datetime, timedelta, timezone
    IST = timezone(timedelta(hours=5, minutes=30))
    from libs.risk.engine import RiskEngine, RiskLimits
    eng = RiskEngine(RiskLimits())  # trading_hours_only=True (default)
    sun = _risk_ctx(now=datetime(2026, 10, 11, 10, 0, tzinfo=IST))   # Sunday
    assert not eng.check_order("BUY", 100, 1000.0, sun).allowed, "Sunday open?"
    mon = _risk_ctx(now=datetime(2026, 10, 12, 10, 0, tzinfo=IST))   # Monday 10:00
    assert eng.check_order("BUY", 100, 1000.0, mon).allowed, "Monday 10:00 band?"
    early = _risk_ctx(now=datetime(2026, 10, 12, 8, 0, tzinfo=IST))
    assert not eng.check_order("BUY", 100, 1000.0, early).allowed, "08:00 open?"
    late = _risk_ctx(now=datetime(2026, 10, 12, 16, 0, tzinfo=IST))
    assert not eng.check_order("BUY", 100, 1000.0, late).allowed, "16:00 open?"
    # trading_hours_only=False → Sunday bhi allowed (replay/simulation)
    eng2 = _risk_engine()
    assert eng2.check_order("BUY", 100, 1000.0, sun).allowed


def t_p4_risk_position_cap():
    eng = _risk_engine()  # max 20% of ₹10L = ₹2L, aur absolute ₹2L
    big = eng.check_order("BUY", 300, 1000.0, _risk_ctx())   # ₹3L > cap
    assert not big.allowed and "position" in big.reason.lower(), big.reason
    ok = eng.check_order("BUY", 100, 1000.0, _risk_ctx())    # ₹1L ≤ cap
    assert ok.allowed


def t_p4_risk_max_positions():
    eng = _risk_engine()
    ctx = _risk_ctx(open_positions=5)
    d = eng.check_order("BUY", 10, 1000.0, ctx)
    assert not d.allowed, "6vi position allowed?"
    # SELL hamesha allowed (kam karne ke liye)
    assert eng.check_order("SELL", 10, 1000.0, ctx).allowed


def t_p4_risk_daily_loss():
    eng = _risk_engine()  # daily loss limit 3%
    assert not eng.check_order("BUY", 10, 1000.0, _risk_ctx(daily_pnl_pct=-3.5)).allowed
    assert eng.check_order("BUY", 10, 1000.0, _risk_ctx(daily_pnl_pct=-2.0)).allowed


def t_p4_risk_drawdown():
    eng = _risk_engine()  # max drawdown 10%
    assert not eng.check_order("BUY", 10, 1000.0, _risk_ctx(current_drawdown_pct=-11.0)).allowed
    assert eng.check_order("BUY", 10, 1000.0, _risk_ctx(current_drawdown_pct=-5.0)).allowed


def t_p4_risk_rate_limit():
    eng = _risk_engine()  # 5 orders/min
    for i in range(5):
        assert eng.check_order("BUY", 10, 1000.0, _risk_ctx()).allowed, f"order {i+1} rejected"
    d = eng.check_order("BUY", 10, 1000.0, _risk_ctx())
    assert not d.allowed and "rate" in d.reason.lower(), d.reason


def t_p4_risk_price_deviation():
    eng = _risk_engine()  # max 10% deviation
    assert not eng.check_order("BUY", 10, 1150.0, _risk_ctx()).allowed  # +15%
    assert eng.check_order("BUY", 10, 1050.0, _risk_ctx()).allowed        # +5%


def t_p4_risk_instrument_whitelist():
    eng = _risk_engine(allowed_instruments=["NSE:INFY"])
    assert not eng.check_order("BUY", 10, 1000.0, _risk_ctx()).allowed  # TESTCO not allowed
    assert eng.check_order("BUY", 10, 1000.0, _risk_ctx(instrument="NSE:INFY")).allowed


def t_p4_risk_min_confidence():
    eng = _risk_engine()  # min 0.6
    assert not eng.check_order("BUY", 10, 1000.0, _risk_ctx(), confidence=0.5).allowed
    assert eng.check_order("BUY", 10, 1000.0, _risk_ctx(), confidence=0.65).allowed
    # confidence na diya toh yeh check skip
    assert eng.check_order("BUY", 10, 1000.0, _risk_ctx()).allowed


def t_p4_risk_audit_trail():
    eng = _risk_engine()
    d = eng.check_order("BUY", 100, 1000.0, _risk_ctx(), strategy="ema_cross", confidence=0.8)
    assert d.allowed
    assert len(d.checks) >= 8, f"audit trail kam hai: {len(d.checks)} checks"
    for c in d.checks:
        assert set(c.keys()) == {"check", "passed", "detail"}, c
    names = {c["check"] for c in d.checks}
    assert {"kill_switch", "price_deviation", "position_value_cap", "rate_limit"} <= names
    # denied decision mein bhi trail ho
    eng.kill()
    d2 = eng.check_order("BUY", 100, 1000.0, _risk_ctx())
    assert not d2.allowed and d2.checks and d2.checks[0]["passed"] is False


def t_p4_evaluator_ema_cross():
    from apps.engine.strategies.evaluator import StrategyEvaluator
    ev = StrategyEvaluator("ema_cross", {"fast_ema": 3, "slow_ema": 6, "quantity": 50})
    for _ in range(8):
        assert ev.on_price(100.0, 0) is None  # flat → no cross
    sig = ev.on_price(120.0, 0)  # jump → fast crosses above slow
    assert sig and sig["side"] == "BUY" and sig["qty"] == 50, sig
    # girte prices → cross down → SELL poori holding
    sig2 = None
    for p in [110.0, 100.0, 95.0, 90.0, 85.0, 80.0, 75.0, 70.0]:
        sig2 = ev.on_price(p, 50) or sig2
    assert sig2 and sig2["side"] == "SELL" and sig2["qty"] == 50, sig2


def t_p4_evaluator_rsi():
    from apps.engine.strategies.evaluator import StrategyEvaluator
    ev = StrategyEvaluator("rsi", {"period": 5, "oversold": 30, "quantity": 20})
    for _ in range(7):
        assert ev.on_price(100.0, 0) is None  # steady → RSI 100 → no signal
    sig = ev.on_price(95.0, 0)  # sharp drop → RSI oversold
    assert sig and sig["side"] == "BUY" and "RSI" in sig["reason"], sig


def t_p4_broker_dry_run():
    from apps.engine.kite_broker import KiteBroker
    b = KiteBroker(dry_run=True)
    assert b.mode == "dry_run"
    assert b.connect()["status"].startswith("connected")
    assert isinstance(b.resolve_token("NSE", "TESTCO"), int)
    b.set_price(1000.0)
    q = b.quote("NSE", "TESTCO")
    assert q["last_price"] == 1000.0
    # BUY → instant COMPLETE at last price
    o = b.place_market_order("NSE", "TESTCO", "BUY", 10)
    assert o["status"] == "COMPLETE" and o["price"] == 1000.0 and o["filled_qty"] == 10
    pos = {p["symbol"]: p for p in b.positions()}
    assert pos["TESTCO"]["qty"] == 10 and pos["TESTCO"]["avg_price"] == 1000.0
    # cancel: dry-run mein sab COMPLETE → NOT_FOUND
    assert b.cancel_order(o["order_id"])["status"] == "NOT_FOUND"
    # square off → position 0
    closed = b.square_off_all()
    assert len(closed) == 1 and closed[0]["side"] == "SELL"
    assert all(p["qty"] == 0 for p in b.positions())
    assert len(b.all_orders()) == 2 and b.open_orders() == []


def t_p4_live_trader_dry_run():
    import asyncio

    from apps.engine.kite_broker import KiteBroker
    from apps.engine.live import LiveTrader, ReplayPriceSource
    from libs.risk.engine import RiskEngine, RiskLimits

    async def run():
        events = []
        broker = KiteBroker(dry_run=True)
        src = ReplayPriceSource("NSE:TESTCO", speed=0, limit=80)
        t = LiveTrader("NSE:TESTCO", "ema_cross", {}, broker=broker,
                       risk_engine=RiskEngine(RiskLimits(trading_hours_only=False)),
                       price_source=src, on_event=lambda e: events.append(e),
                       capital=1_000_000)
        await t.start()
        assert t.running
        await asyncio.wait_for(t._task, timeout=30)
        await asyncio.sleep(0.2)  # _emit_soon events flush
        s = t.state()
        assert s["mode"] == "dry_run"
        assert s["running"] is False, "replay khatam hone ke baad bhi running"
        assert len(s["equity_curve"]) > 10, "kam ticks"
        # 💰 cash invariant from broker order ledger
        cash = 1_000_000.0
        n_filled = 0
        for o in broker.all_orders():
            if o["status"] == "COMPLETE":
                n_filled += 1
                cash += o["qty"] * o["price"] * (1 if o["side"] == "SELL" else -1)
        assert n_filled >= 1, "koi order nahi hua"
        assert abs(s["cash"] - cash) < 0.01, f"cash mismatch: {s['cash']} vs {cash}"
        # har order risk engine se hokar gaya
        for e in events:
            if e["type"] == "live.order":
                assert e["risk"]["allowed"] is True
        types = {e["type"] for e in events}
        assert "live.started" in types and "live.finished" in types, types

    asyncio.run(run())


def t_p4_live_kill_switch():
    import asyncio

    from apps.engine.kite_broker import KiteBroker
    from apps.engine.live import LiveTrader, ReplayPriceSource
    from libs.risk.engine import RiskEngine, RiskLimits

    async def run():
        broker = KiteBroker(dry_run=True)
        src = ReplayPriceSource("NSE:TESTCO", speed=0.01, limit=150)
        t = LiveTrader("NSE:TESTCO", "ema_cross",
                       {"fast_ema": 3, "slow_ema": 6, "quantity": 10},
                       broker=broker,
                       risk_engine=RiskEngine(RiskLimits(trading_hours_only=False)),
                       price_source=src, capital=1_000_000)
        await t.start()
        bought = False
        for _ in range(200):  # ~4s — chhoti EMAs se jaldi cross ho jayega
            if any(o["side"] == "BUY" for o in broker.all_orders()):
                bought = True
                break
            await asyncio.sleep(0.02)
        assert bought, "kill test: koi BUY nahi hua"
        t.kill()
        s = t.state()
        assert s["killed"] is True and s["running"] is False
        assert s["risk_killed"] is True, "risk engine kill nahi hua"
        assert all(p["qty"] == 0 for p in s["positions"]), "kill: positions open hain"
        # kill ke baad koi naya order nahi
        assert not t.risk.check_order("BUY", 10, 1000.0, _risk_ctx()).allowed

    asyncio.run(run())


check("risk: kill switch blocks + reset", t_p4_risk_kill_switch)
check("risk: trading hours (IST, Mon-Fri 09:15-15:30)", t_p4_risk_trading_hours)
check("risk: position value cap (20% / ₹2L)", t_p4_risk_position_cap)
check("risk: max open positions (5)", t_p4_risk_max_positions)
check("risk: daily loss limit (3%)", t_p4_risk_daily_loss)
check("risk: max drawdown (10%)", t_p4_risk_drawdown)
check("risk: order rate limit (5/min)", t_p4_risk_rate_limit)
check("risk: price deviation (10%)", t_p4_risk_price_deviation)
check("risk: instrument whitelist", t_p4_risk_instrument_whitelist)
check("risk: AI min confidence (0.6)", t_p4_risk_min_confidence)
check("risk: audit trail (>=8 checks)", t_p4_risk_audit_trail)
check("evaluator: ema_cross BUY→SELL", t_p4_evaluator_ema_cross)
check("evaluator: rsi oversold BUY", t_p4_evaluator_rsi)
check("kite broker: dry-run fill/positions/square-off", t_p4_broker_dry_run)
check("live trader: dry-run headless (cash invariant)", t_p4_live_trader_dry_run)
check("live trader: kill switch (square-off + risk kill)", t_p4_live_kill_switch)

# ============================================================
print("\n📦 PHASE 5 — OSS Release (packaging, docker, CI, community)")
# ============================================================

def t_p5_packaging():
    import tomllib
    with open(ROOT / "pyproject.toml", "rb") as f:
        pp = tomllib.load(f)
    assert pp["project"]["name"] == "ai-quant-platform"
    assert pp["project"]["version"] == "0.5.0"
    assert pp["project"]["license"]["text"] == "MIT"
    scripts = pp["project"]["scripts"]
    assert set(scripts) == {"aiq-data", "aiq-engine", "aiq-agent", "aiq-api"}, scripts
    # har entry point ka target importable + callable
    import importlib
    for target in scripts.values():
        mod_name, attr = target.split(":")
        mod = importlib.import_module(mod_name)
        assert callable(getattr(mod, attr)), f"{target} not callable"
    # core deps declare ho
    deps = pp["project"]["dependencies"]
    for d in ["pydantic", "pyarrow", "nautilus_trader", "fastapi", "uvicorn"]:
        assert any(d in x for x in deps), f"missing dep {d}"
    # optional extras
    assert "kiteconnect" in " ".join(pp["project"]["optional-dependencies"]["kite"])
    assert "litellm" in " ".join(pp["project"]["optional-dependencies"]["llm"])


def t_p5_docker_stack():
    import yaml
    with open(ROOT / "docker-compose.yml") as f:
        dc = yaml.safe_load(f)
    svcs = dc["services"]
    assert set(svcs) == {"api", "dashboard"}, svcs.keys()
    assert "8000:8000" in svcs["api"]["ports"]
    assert "5173:80" in svcs["dashboard"]["ports"]
    assert svcs["api"]["build"] == "."
    assert svcs["dashboard"]["build"] == "./apps/dashboard"
    assert "healthcheck" in svcs["api"]
    # dashboard nginx proxy: /api strip + /ws websocket
    nginx = (ROOT / "apps" / "dashboard" / "nginx.conf").read_text()
    assert "proxy_pass http://api:8000/;" in nginx, "api proxy prefix strip missing"
    assert "location /ws" in nginx and "Upgrade $http_upgrade" in nginx
    # root Dockerfile: healthcheck + aiq-api default
    df = (ROOT / "Dockerfile").read_text()
    assert "HEALTHCHECK" in df and 'CMD ["aiq-api"]' in df
    # .dockerignore: data aur secrets bahar
    di = (ROOT / ".dockerignore").read_text()
    for x in ["data/", ".env", "node_modules/", "*.egg-info/"]:
        assert x in di, f".dockerignore missing {x}"


def t_p5_env_example_safe():
    env = (ROOT / ".env.example").read_text()
    # live trading default DISABLED (commented out)
    assert "# LIVE_TRADING_ENABLED=true" in env, "live gate must be commented (disabled) by default"
    assert "LIVE_MAX_CAPITAL=50000" in env
    assert "KITE_API_KEY" in env and "KITE_ACCESS_TOKEN" in env
    # koi real secret nahi — sirf placeholders
    assert "your_api_key" in env and "your-key" in env
    # .env git-ignored hai (secrets kabhi commit nahi)
    gi = (ROOT / ".gitignore").read_text()
    assert ".env" in gi.split(), ".env not git-ignored!"
    assert "*.egg-info/" in gi


def t_p5_ci_workflow():
    import yaml
    wf = ROOT / ".github" / "workflows" / "ci.yml"
    assert wf.exists(), "ci.yml missing"
    with open(wf) as f:
        ci = yaml.safe_load(f)
    jobs = ci["jobs"]
    assert set(jobs) == {"test", "lint", "docker"}, jobs.keys()
    assert "test_all.py" in str(ci), "CI must run the test suite"
    assert "ruff check" in str(ci), "CI must lint"
    assert "docker compose build" in str(ci), "CI must build docker images"


def t_p5_community_files():
    for f in ["LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md",
              "SAFETY.md", "README.md"]:
        assert (ROOT / f).exists(), f"{f} missing"
    lic = (ROOT / "LICENSE").read_text()
    assert "MIT License" in lic
    sec = (ROOT / "SECURITY.md").read_text()
    assert "real money" in sec.lower(), "SECURITY.md must mention real money"
    # issue templates + PR template
    it = ROOT / ".github" / "ISSUE_TEMPLATE"
    assert (it / "bug_report.md").exists() and (it / "feature_request.md").exists()
    prt = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text()
    assert "Safety checklist" in prt, "PR template must have safety checklist"


def t_p5_demo_phase4():
    r = subprocess.run([sys.executable, "scripts/demo_phase4.py"],
                       capture_output=True, text=True, cwd=ROOT, timeout=90)
    assert r.returncode == 0, f"demo failed: {r.stderr[-500:]}"
    assert "Risk Engine" in r.stdout and "Kill Switch" in r.stdout
    assert "REJECT" in r.stdout, "risk rejections not shown"
    assert "DRY-RUN" in r.stdout or "dry-run" in r.stdout.lower()


check("packaging: pyproject + entry points", t_p5_packaging)
check("docker: compose + Dockerfiles + nginx + dockerignore", t_p5_docker_stack)
check("env: .env.example safe defaults + .env git-ignored", t_p5_env_example_safe)
check("CI: workflow (test + lint + docker)", t_p5_ci_workflow)
check("community: LICENSE/CONTRIBUTING/SECURITY/templates", t_p5_community_files)
check("demo: phase4 dry-run script runs", t_p5_demo_phase4)

# ============================================================
print("\n🏭 PHASE 6 — Multi-Broker (Kite + Dhan) + Live Dashboard")
# ============================================================

def t_p6_broker_base_conformance():
    from apps.engine.brokers import BrokerBase, available_brokers, get_broker
    # registry mein dono brokers
    names = {b["name"] for b in available_brokers()}
    assert {"kite", "dhan"} <= names, names
    # factory se dono instantiate (ABC pura implement kiya hai)
    for name in ("kite", "dhan"):
        b = get_broker(name, dry_run=True)
        assert isinstance(b, BrokerBase), name
        assert b.dry_run is True and b.is_live is False
        assert b.mode == "dry_run"
        # interface ke saare methods maujood
        for m in ("connect", "resolve_token", "quote", "place_market_order",
                  "cancel_order", "open_orders", "all_orders", "positions",
                  "margins", "square_off_all", "set_price"):
            assert callable(getattr(b, m)), f"{name}.{m} missing"
    # unknown broker → ValueError
    try:
        get_broker("upstox")
        raise AssertionError("unknown broker allowed")
    except ValueError as e:
        assert "upstox" in str(e)
    # purana import path (shim) abhi bhi chalega
    from apps.engine.brokers.kite_broker import KiteBroker
    from apps.engine.kite_broker import KiteBroker as ShimKite
    assert ShimKite is KiteBroker


def t_p6_dhan_broker_dry_run():
    from apps.engine.brokers import get_broker
    b = get_broker("dhan", dry_run=True)
    assert b.name == "dhan"
    assert b.connect()["status"].startswith("connected")
    # dhan security_id = string
    token = b.resolve_token("NSE", "TESTCO")
    assert isinstance(token, str) and token.isdigit()
    b.set_price(500.0)
    q = b.quote("NSE", "TESTCO")
    assert q["last_price"] == 500.0 and q["source"] == "dry_run"
    # BUY → instant COMPLETE at last price
    o = b.place_market_order("NSE", "TESTCO", "BUY", 10)
    assert o["status"] == "COMPLETE" and o["price"] == 500.0 and o["filled_qty"] == 10
    pos = {p["symbol"]: p for p in b.positions()}
    assert pos["TESTCO"]["qty"] == 10 and pos["TESTCO"]["avg_price"] == 500.0
    # segment/product mapping
    assert b._segment("NSE") == "NSE_EQ" and b._product("CNC") == "CNC" and b._product("MIS") == "INTRA"
    # cancel: dry-run mein sab COMPLETE → NOT_FOUND
    assert b.cancel_order(o["order_id"])["status"] == "NOT_FOUND"
    # square off → position 0
    closed = b.square_off_all()
    assert len(closed) == 1 and closed[0]["side"] == "SELL"
    assert all(p["qty"] == 0 for p in b.positions())
    assert len(b.all_orders()) == 2 and b.open_orders() == []
    # unsupported exchange → error
    try:
        b._segment("NSE_FNO")
        raise AssertionError("F&O segment allowed (MVP mein nahi)")
    except ValueError:
        pass


def t_p6_dhan_live_trader_dry_run():
    import asyncio

    from apps.engine.brokers import get_broker
    from apps.engine.live import LiveTrader, ReplayPriceSource
    from libs.risk.engine import RiskEngine, RiskLimits

    async def run():
        events = []
        broker = get_broker("dhan", dry_run=True)
        src = ReplayPriceSource("NSE:TESTCO", speed=0, limit=80)
        t = LiveTrader("NSE:TESTCO", "ema_cross", {}, broker=broker,
                       risk_engine=RiskEngine(RiskLimits(trading_hours_only=False)),
                       price_source=src, on_event=lambda e: events.append(e),
                       capital=1_000_000)
        await t.start()
        await asyncio.wait_for(t._task, timeout=30)
        await asyncio.sleep(0.2)
        s = t.state()
        assert s["mode"] == "dry_run" and s["running"] is False
        assert len(s["equity_curve"]) > 10
        # 💰 cash invariant from broker ledger
        cash = 1_000_000.0
        n = 0
        for o in broker.all_orders():
            if o["status"] == "COMPLETE":
                n += 1
                cash += o["qty"] * o["price"] * (1 if o["side"] == "SELL" else -1)
        assert n >= 1, "dhan: koi order nahi hua"
        assert abs(s["cash"] - cash) < 0.01, f"dhan cash mismatch: {s['cash']} vs {cash}"
        # har order risk se hokar gaya
        for e in events:
            if e["type"] == "live.order":
                assert e["risk"]["allowed"] is True

    asyncio.run(run())


def t_p6_available_brokers_info():
    from apps.engine.brokers import available_brokers
    info = {b["name"]: b for b in available_brokers()}
    assert info["kite"]["required_env"] == ["KITE_API_KEY"]
    assert info["dhan"]["required_env"] == ["DHAN_CLIENT_ID"]
    # sandbox mein creds nahi hain
    assert info["kite"]["credentials_present"] is False
    assert info["dhan"]["credentials_present"] is False


def t_p6_cli_live_broker():
    # dhan dry-run via CLI
    r = subprocess.run([sys.executable, "-m", "apps.engine.main", "live",
                        "--instrument", "NSE:TESTCO", "--strategy", "ema_cross",
                        "--mode", "dry_run", "--broker", "dhan",
                        "--speed", "0", "--limit", "60"],
                       capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert r.returncode == 0, f"dhan CLI failed: {r.stderr[-400:]}"
    assert "Live Trader (dry_run)" in r.stdout
    # unknown broker → non-zero exit
    r2 = subprocess.run([sys.executable, "-m", "apps.engine.main", "live",
                         "--instrument", "NSE:TESTCO", "--broker", "upstox"],
                        capture_output=True, text=True, cwd=ROOT, timeout=30)
    assert r2.returncode != 0 and "upstox" in (r2.stdout + r2.stderr)
    # kite abhi bhi default
    r3 = subprocess.run([sys.executable, "-m", "apps.engine.main", "live",
                         "--instrument", "NSE:TESTCO", "--mode", "dry_run",
                         "--speed", "0", "--limit", "40"],
                        capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert r3.returncode == 0, f"kite CLI failed: {r3.stderr[-400:]}"


def t_p6_pyproject_dhan_extra():
    import tomllib
    with open(ROOT / "pyproject.toml", "rb") as f:
        pp = tomllib.load(f)
    extras = pp["project"]["optional-dependencies"]
    assert "dhanhq" in " ".join(extras["dhan"]), "dhan extra missing"
    assert "dhanhq" in " ".join(extras["all"]), "all extra mein dhanhq missing"
    # .env.example mein dhan creds hain (commented)
    env = (ROOT / ".env.example").read_text()
    assert "# DHAN_CLIENT_ID=" in env and "# DHAN_ACCESS_TOKEN=" in env


def t_p6_dashboard_build():
    dash = ROOT / "apps" / "dashboard"
    if not (dash / "node_modules" / ".bin" / "vite").exists():
        skip("dashboard build", "node_modules nahi — npm install karo")
        return
    r = subprocess.run(["npm", "run", "build"], capture_output=True, text=True,
                       cwd=dash, timeout=180)
    assert r.returncode == 0, f"build failed: {r.stderr[-500:]}"
    assert (dash / "dist" / "index.html").exists()
    # Live page bundle mein hai
    js = list((dash / "dist" / "assets").glob("*.js"))
    assert js, "no JS bundle"
    assert "Live Trading" in js[0].read_text(errors="ignore"), "Live page missing from bundle"


check("brokers: base conformance + factory + shim", t_p6_broker_base_conformance)
check("brokers: dhan dry-run (fill/positions/square-off)", t_p6_dhan_broker_dry_run)
check("brokers: dhan live trader dry-run (cash invariant)", t_p6_dhan_live_trader_dry_run)
check("brokers: available_brokers info", t_p6_available_brokers_info)
check("CLI: live --broker dhan (dry-run + invalid)", t_p6_cli_live_broker)
check("packaging: dhan extra + .env.example", t_p6_pyproject_dhan_extra)
check("dashboard: production build with Live page", t_p6_dashboard_build)

# ============================================================
print("\n🌐 PHASE 3 — API + Dashboard (live servers)")
# ============================================================

def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def http_post(url, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def api_up() -> bool:
    try:
        return http_get(API + "/health")["status"] == "ok"
    except Exception:
        return False


if not api_up():
    for name in ["API health", "API instruments", "API strategies", "API data fetch",
                 "API backtest run", "API backtests list", "API analyze+approve+reject",
                 "API paper flow (start→stop→kill)", "dashboard proxy + preview host",
                 "API live dry-run flow (start→status→stop)",
                 "API live gates (live mode blocked without env)",
                 "API kill-switch kills live too",
                 "API brokers list (kite + dhan)",
                 "API live dhan dry-run + invalid broker gate"]:
        skip(name, "API server nahi chal raha (python -m apps.api.main)")
else:
    def t_api_health():
        assert http_get(API + "/health")["status"] == "ok"

    def t_api_instruments():
        insts = http_get(API + "/instruments")["instruments"]
        assert len(insts) > 0, "no instruments"
        assert any(i["instrument"] == "NSE:TESTCO" for i in insts)

    def t_api_strategies():
        s = http_get(API + "/strategies")["strategies"]
        assert "ema_cross" in s and "rsi" in s

    def t_api_data_fetch():
        r = http_post(API + "/data/fetch", {"provider": "mock", "symbol": "APITEST", "days": 30})
        assert r["candles"] == 30, r
        c = http_get(API + "/data/candles?instrument=NSE:APITEST&limit=5")
        assert len(c["candles"]) == 5

    def t_api_backtest_run():
        r = http_post(API + "/backtests", {"instrument": "NSE:TESTCO", "strategy": "ema_cross",
                                           "params": {"fast_ema": 5, "slow_ema": 20},
                                           "capital": 500_000})
        assert r["instrument"] == "NSE:TESTCO" and r["days"] > 0
        assert r["params"]["fast_ema"] == 5

    def t_api_backtests_list():
        lst = http_get(API + "/backtests")["backtests"]
        assert len(lst) > 0, "no saved backtests"

    def t_api_analyze_approve_reject():
        run = http_post(API + "/agent/analyze", {"instrument": "NSE:INFY", "llm": "mock"})["run"]
        rid = run["id"]
        assert run["final_signal"]["direction"] in ("BUY", "SELL", "HOLD")
        assert len(run["steps"]) == 3
        a = http_post(API + f"/signals/{rid}/approve")
        assert a["run"]["final_signal"]["status"] == "approved"
        run2 = http_post(API + "/agent/analyze", {"instrument": "NSE:INFY", "llm": "mock"})["run"]
        x = http_post(API + f"/signals/{run2['id']}/reject")
        assert x["run"]["final_signal"]["status"] == "rejected"

    def t_api_paper_flow():
        http_post(API + "/paper/start", {"instrument": "NSE:TESTCO", "strategy": "ema_cross",
                                         "speed": 0.1, "limit": 40, "capital": 500_000})
        # double-start → 400 hona chahiye
        try:
            http_post(API + "/paper/start", {"instrument": "NSE:TESTCO", "strategy": "ema_cross",
                                             "speed": 0.1, "limit": 40})
            raise AssertionError("double-start allowed (expected 400)")
        except urllib.error.HTTPError as e:
            assert e.code == 400, f"expected 400, got {e.code}"
        time.sleep(3)
        p = http_get(API + "/portfolio")
        assert p["running"] is True, "paper not running"
        assert p["initial_capital"] == 500_000
        assert len(p["equity_curve"]) > 0, "no equity ticks"
        http_post(API + "/paper/stop")
        time.sleep(0.5)
        assert http_get(API + "/portfolio")["running"] is False, "stop failed"
        # kill switch flow
        http_post(API + "/paper/start", {"instrument": "NSE:TESTCO", "strategy": "ema_cross",
                                         "speed": 0.1, "limit": 60})
        time.sleep(1.5)
        http_post(API + "/kill-switch")
        time.sleep(0.5)
        p3 = http_get(API + "/portfolio")
        assert p3["killed"] is True and p3["running"] is False
        assert all(pos["qty"] == 0 for pos in p3["positions"]), "kill: positions not closed"

    def t_dashboard():
        # vite proxy: /api → backend
        assert http_get(DASH + "/api/health")["status"] == "ok"
        # vite serves the app
        with urllib.request.urlopen(DASH + "/", timeout=10) as r:
            body = r.read().decode()
            assert r.status == 200 and "root" in body

    check("API health", t_api_health)
    check("API instruments", t_api_instruments)
    check("API strategies", t_api_strategies)
    check("API data fetch (mock) + candles", t_api_data_fetch)
    check("API backtest run", t_api_backtest_run)
    check("API backtests list", t_api_backtests_list)
    check("API analyze + approve + reject", t_api_analyze_approve_reject)
    check("API paper flow (start→stop→kill)", t_api_paper_flow)
    check("dashboard proxy + serve", t_dashboard)

    def t_api_live_dry_run_flow():
        r = http_post(API + "/live/start", {"instrument": "NSE:TESTCO", "strategy": "ema_cross",
                                            "mode": "dry_run", "capital": 1_000_000,
                                            "speed": 0.05, "limit": 60})
        assert r["status"] == "started" and r["mode"] == "dry_run", r
        # double-start → 400
        try:
            http_post(API + "/live/start", {"instrument": "NSE:TESTCO", "mode": "dry_run"})
            raise AssertionError("double-start allowed (expected 400)")
        except urllib.error.HTTPError as e:
            assert e.code == 400, f"expected 400, got {e.code}"
        time.sleep(2)
        s = http_get(API + "/live/status")
        assert s["running"] is True, "live trader not running"
        assert s["mode"] == "dry_run"
        assert len(s["equity_curve"]) > 0, "no ticks"
        assert s["risk_killed"] is False
        http_post(API + "/live/stop")
        time.sleep(0.5)
        assert http_get(API + "/live/status")["running"] is False, "stop failed"

    def t_api_live_gates():
        # live mode without LIVE_TRADING_ENABLED → 400
        try:
            http_post(API + "/live/start", {"instrument": "NSE:TESTCO", "mode": "live",
                                            "capital": 10_000,
                                            "confirm": "I UNDERSTAND THIS TRADES REAL MONEY"})
            raise AssertionError("live start allowed without env gate (expected 400)")
        except urllib.error.HTTPError as e:
            assert e.code == 400, f"expected 400, got {e.code}"
            assert "LIVE" in e.read().decode(), "gate ka reason nahi mila"
        # invalid mode → 400
        try:
            http_post(API + "/live/start", {"instrument": "NSE:TESTCO", "mode": "yolo"})
            raise AssertionError("invalid mode allowed (expected 400)")
        except urllib.error.HTTPError as e:
            assert e.code == 400, f"expected 400, got {e.code}"
        # health mein live trading disabled dikhna chahiye
        h = http_get(API + "/health")
        assert h["live_trading_enabled"] is False
        assert h["live_max_capital"] == 50_000

    def t_api_kill_switch_live():
        http_post(API + "/live/start", {"instrument": "NSE:TESTCO", "strategy": "ema_cross",
                                        "params": {"fast_ema": 3, "slow_ema": 6, "quantity": 10},
                                        "mode": "dry_run", "capital": 1_000_000,
                                        "speed": 0.02, "limit": 150})
        time.sleep(2)  # kuch orders ho jayenge
        http_post(API + "/kill-switch")
        time.sleep(0.5)
        s = http_get(API + "/live/status")
        assert s["killed"] is True and s["running"] is False, "live not killed"
        assert s["risk_killed"] is True, "risk engine not killed"
        assert all(p["qty"] == 0 for p in s["positions"]), "kill: live positions open hain"

    check("API live dry-run flow (start→status→stop)", t_api_live_dry_run_flow)
    check("API live gates (live mode blocked without env)", t_api_live_gates)
    check("API kill-switch kills live too", t_api_kill_switch_live)

    def t_api_brokers():
        r = http_get(API + "/brokers")
        names = {b["name"] for b in r["brokers"]}
        assert {"kite", "dhan"} <= names, names
        info = {b["name"]: b for b in r["brokers"]}
        assert info["kite"]["required_env"] == ["KITE_API_KEY"]
        assert info["dhan"]["required_env"] == ["DHAN_CLIENT_ID"]
        # sandbox mein creds nahi — live disabled bhi dikhe
        assert r["live_trading_enabled"] is False

    def t_api_live_dhan_dry_run():
        # dhan broker, dry_run → chalega (replay prices, simulated orders)
        r = http_post(API + "/live/start", {"instrument": "NSE:TESTCO",
                                            "strategy": "ema_cross",
                                            "mode": "dry_run", "broker": "dhan",
                                            "capital": 1_000_000, "speed": 0.05,
                                            "limit": 60})
        assert r["status"] == "started" and r["broker"] == "dhan", r
        time.sleep(1.5)
        s = http_get(API + "/live/status")
        assert s["running"] is True and s["mode"] == "dry_run"
        assert len(s["equity_curve"]) > 0
        http_post(API + "/live/stop")
        # invalid broker → 400
        try:
            http_post(API + "/live/start", {"instrument": "NSE:TESTCO",
                                            "mode": "dry_run", "broker": "upstox"})
            raise AssertionError("invalid broker allowed (expected 400)")
        except urllib.error.HTTPError as e:
            assert e.code == 400, f"expected 400, got {e.code}"
        # live mode with dhan but no env gate → 400
        try:
            http_post(API + "/live/start", {"instrument": "NSE:TESTCO", "mode": "live",
                                            "broker": "dhan", "capital": 10_000,
                                            "confirm": "I UNDERSTAND THIS TRADES REAL MONEY"})
            raise AssertionError("dhan live allowed without env gate (expected 400)")
        except urllib.error.HTTPError as e:
            assert e.code == 400, f"expected 400, got {e.code}"

    check("API brokers list (kite + dhan)", t_api_brokers)
    check("API live dhan dry-run + invalid broker gate", t_api_live_dhan_dry_run)

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok is True)
failed = sum(1 for _, ok, _ in results if ok is False)
skipped = sum(1 for _, ok, _ in results if ok is None)
print(f"📊 TEST SUMMARY: {passed} passed · {failed} failed · {skipped} skipped (total {len(results)})")
if failed:
    print("\n❌ Failed tests:")
    for name, ok, err in results:
        if ok is False:
            print(f"   • {name}: {err}")
print("=" * 60)
sys.exit(1 if failed else 0)
