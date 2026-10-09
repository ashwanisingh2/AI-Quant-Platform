"""Phase 4 demo: Risk Engine + Live Trading (Kite dry-run) — bina paisa lagaye.

Kya dikhata hai:
  1. Risk engine — har rule ek-ek karke (kill, hours, caps, limits...)
  2. Kite broker dry-run — fills, positions, square-off
  3. LiveTrader dry-run — replay prices + simulated orders + risk gate
  4. Kill switch — sab band, positions square off

⚠️ Ye 100% SAFE hai — dry_run mode, koi real order nahi jayega.
Live (real money) ke liye SAFETY.md padho + 4 gates enable karo.

Run:  python scripts/demo_phase4.py
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root

from apps.engine.kite_broker import KiteBroker
from apps.engine.live import LiveTrader, ReplayPriceSource
from libs.risk.engine import RiskContext, RiskEngine, RiskLimits

IST = timezone(timedelta(hours=5, minutes=30))


def ctx(**kw) -> RiskContext:
    base = dict(capital=1_000_000, cash=1_000_000, positions_value=0.0,
                open_positions=0, daily_pnl_pct=0.0, current_drawdown_pct=0.0,
                reference_price=1000.0, instrument="NSE:TESTCO",
                now=datetime(2026, 10, 12, 10, 0, tzinfo=IST))  # Monday 10:00 IST
    base.update(kw)
    return RiskContext(**base)


def demo_risk_engine():
    print("=" * 74)
    print("🛡️  PART 1 — Risk Engine (11 checks, audit trail ke saath)")
    print("=" * 74)
    eng = RiskEngine(RiskLimits())

    cases = [
        ("Normal BUY (Monday 10:00)", "BUY", 100, 1000.0, ctx(), None),
        ("Sunday 10:00", "BUY", 100, 1000.0,
         ctx(now=datetime(2026, 10, 11, 10, 0, tzinfo=IST)), None),
        ("Position 300K > 200K cap", "BUY", 300, 1000.0, ctx(), None),
        ("Price +15% deviation", "BUY", 10, 1150.0, ctx(), None),
        ("5th position (max=5)", "BUY", 10, 1000.0, ctx(open_positions=5), None),
        ("Daily loss -3.5%", "BUY", 10, 1000.0, ctx(daily_pnl_pct=-3.5), None),
        ("Drawdown -11%", "BUY", 10, 1000.0, ctx(current_drawdown_pct=-11.0), None),
        ("AI confidence 0.5", "BUY", 10, 1000.0, ctx(), 0.5),
    ]
    for label, side, qty, price, c, conf in cases:
        d = eng.check_order(side, qty, price, c, confidence=conf)
        emoji = "✅ ALLOW" if d.allowed else "🛡️  REJECT"
        print(f"  {emoji}  {label:32s} → {d.reason}")

    eng.kill()
    d = eng.check_order("BUY", 100, 1000.0, ctx())
    print(f"  🚨 KILL SWITCH  {'':27s} → {d.reason}")
    eng.reset_kill()

    d = eng.check_order("BUY", 100, 1000.0, ctx(), confidence=0.8)
    print(f"\n  📋 Audit trail ({len(d.checks)} checks):")
    for c in d.checks:
        print(f"     {'✓' if c['passed'] else '✗'} {c['check']:22s} {c['detail']}")


def demo_broker_dry_run():
    print("\n" + "=" * 74)
    print("🔌 PART 2 — Kite Broker (dry_run: real prices, simulated orders)")
    print("=" * 74)
    b = KiteBroker(dry_run=True)
    print(f"  Mode: {b.mode} · connect: {b.connect()['status']}")
    b.set_price(1000.0)
    o = b.place_market_order("NSE", "TESTCO", "BUY", 10)
    print(f"  🟢 BUY 10 @ ₹{o['price']} → {o['status']} (order {o['order_id']})")
    print(f"  📦 Position: {b.positions()}")
    closed = b.square_off_all()
    print(f"  🚨 Square-off: {len(closed)} order → {b.positions()}")
    print("  ⚠️  Live mode (real money) → 4 gates: env + confirm + max capital + Kite creds")


async def demo_live_trader():
    print("\n" + "=" * 74)
    print("🤖 PART 3 — LiveTrader (dry-run: replay prices → risk gate → broker)")
    print("=" * 74)
    events: list[dict] = []

    def on_event(e):
        events.append(e)
        if e["type"] == "live.order":
            o = e["order"]
            emoji = "🟢" if o["side"] == "BUY" else "🔴"
            print(f"  {emoji} ORDER {o['side']} {o['qty']} @ ₹{o['price']} ({o['status']}) — risk: {e['risk']['reason']}")
        elif e["type"] == "live.rejected":
            print(f"  🛡️  RISK REJECTED: {e['reason']}")

    broker = KiteBroker(dry_run=True)
    src = ReplayPriceSource("NSE:TESTCO", speed=0, limit=80)
    trader = LiveTrader("NSE:TESTCO", "ema_cross", {}, broker=broker,
                        risk_engine=RiskEngine(RiskLimits(trading_hours_only=False)),
                        price_source=src, on_event=on_event, capital=1_000_000)
    await trader.start()
    print(f"  ▶ Started ({broker.mode}) — replaying 80 candles...")
    await asyncio.wait_for(trader._task, timeout=30)
    await asyncio.sleep(0.2)
    s = trader.state()
    print(f"\n  📊 Result: equity ₹{s['current_equity']:,.2f} · P&L {s['total_pnl_pct']:+.2f}% · "
          f"orders {len(broker.all_orders())} · curve {len(s['equity_curve'])} pts")

    print("\n" + "=" * 74)
    print("🚨 PART 4 — Kill Switch (sab band + square off)")
    print("=" * 74)
    trader2 = LiveTrader("NSE:TESTCO", "ema_cross",
                         {"fast_ema": 3, "slow_ema": 6, "quantity": 10},
                         broker=KiteBroker(dry_run=True),
                         risk_engine=RiskEngine(RiskLimits(trading_hours_only=False)),
                         price_source=ReplayPriceSource("NSE:TESTCO", speed=0.01, limit=150),
                         capital=1_000_000)
    await trader2.start()
    for _ in range(200):
        if any(o["side"] == "BUY" for o in trader2.broker.all_orders()):
            break
        await asyncio.sleep(0.02)
    print(f"  Position before kill: {trader2.broker.positions()}")
    trader2.kill()
    s2 = trader2.state()
    print(f"  After kill: killed={s2['killed']} · risk_killed={s2['risk_killed']} · "
          f"positions={s2['positions']}")


def main():
    print("🚀 Phase 4 Demo — Risk Engine + Live Trading (DRY-RUN, 100% safe)")
    print("   Real money nahi lagega. Live ke liye SAFETY.md padho.\n")
    demo_risk_engine()
    demo_broker_dry_run()
    asyncio.run(demo_live_trader())
    print("\n" + "=" * 74)
    print("✅ Demo complete! Agla step: python scripts/test_all.py (40 tests)")
    print("=" * 74)


if __name__ == "__main__":
    main()
