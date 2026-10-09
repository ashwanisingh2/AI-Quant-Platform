"""Engine CLI — backtest chalao.

Usage:
  python -m apps.engine.main strategies
  python -m apps.engine.main backtest --instrument NSE:TESTCO --strategy ema_cross
  python -m apps.engine.main backtest --instrument NSE:INFY --strategy rsi --from 2026-08-01
  python -m apps.engine.main backtest --instrument NSE:TESTCO --strategy ema_cross --set fast_ema=5 --set slow_ema=20
"""
from __future__ import annotations

import argparse
from datetime import date

from apps.engine.runner import run_backtest, save_results
from apps.engine.strategies import STRATEGIES
from libs.shared.charts import sparkline


def parse_set(pairs: list[str] | None) -> dict:
    """['fast_ema=5', 'oversold=35.0'] → {'fast_ema': 5, 'oversold': 35.0}"""
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        if not v:
            raise SystemExit(f"❌ --set format galat hai: {p!r} (use: key=value)")
        try:
            out[k] = int(v)
        except ValueError:
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
    return out


def cmd_strategies(args) -> None:
    print("📚 Available strategies:\n")
    for name, spec in STRATEGIES.items():
        params = ", ".join(f"{k}={v}" for k, v in spec["defaults"].items())
        print(f"  {name:<12} — {spec['description']}")
        print(f"  {'':<12}   defaults: {params}\n")


def cmd_backtest(args) -> None:
    params = parse_set(args.set)
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    print(f"⏳ Running backtest: {args.instrument} · {args.strategy} ...\n")
    results = run_backtest(
        instrument=args.instrument,
        strategy_name=args.strategy,
        params=params,
        start=start,
        end=end,
        capital=args.capital,
    )

    path = save_results(results)
    params_str = ", ".join(f"{k}={v}" for k, v in results["params"].items())
    ret = results["total_return_pct"]
    ret_str = f"{'+' if ret >= 0 else ''}{ret}%"
    sharpe = results["sharpe_ratio"]
    winrate = results["win_rate_pct"]

    print(f"📊 Backtest Results — {results['instrument']} · {results['strategy']}")
    print(f"   Params : {params_str}")
    print(f"   Period : {results['start']} → {results['end']} ({results['days']} days)")
    print(f"   Capital: ₹{results['initial_capital']:,.0f}")
    print("   " + "─" * 44)
    print(f"   Total return  : {ret_str}")
    print(f"   Final equity  : ₹{results['final_equity']:,.2f}")
    print(f"   Max drawdown  : {results['max_drawdown_pct']}%")
    print(f"   Sharpe ratio  : {sharpe if sharpe is not None else 'n/a'}")
    print(f"   Trades        : {results['n_trades']}")
    print(f"   Win rate      : {f'{winrate}%' if winrate is not None else 'n/a'}")
    print("   " + "─" * 44)
    print(f"   Equity curve  : {sparkline(results['equity_curve'], width=50)}")
    print(f"\n💾 Saved: {path}")


def cmd_paper(args) -> None:
    import asyncio

    from apps.engine.paper import PaperTrader

    async def run():
        def on_event(ev):
            if ev["type"] == "paper.order":
                o = ev["order"]
                emoji = "🟢" if o["side"] == "BUY" else "🔴"
                print(f"   {emoji} ORDER: {o['side']} {o['qty']} @ ₹{o['price']} — {o['reason']}")
            elif ev["type"] == "paper.rejected":
                print(f"   ⚠️  REJECTED: {ev['reason']}")
            elif ev["type"] == "paper.tick" and args.verbose:
                print(f"   tick {ev['time']} · ₹{ev['price']} · equity ₹{ev['equity']:,.0f}")
            elif ev["type"] in ("paper.started", "paper.finished"):
                print(f"   ▶ {ev['type']}")

        trader = PaperTrader(args.instrument, args.strategy, parse_set(args.set),
                             capital=args.capital, speed=args.speed,
                             on_event=on_event, limit=args.limit)
        await trader.start()
        if trader._task:
            await trader._task
        s = trader.state()
        print(f"\n📊 Paper Trading Result — {s['instrument']} · {s['strategy']}")
        print(f"   Orders: {s['n_orders']} · Final equity: ₹{s['current_equity']:,.2f} "
              f"· P&L: {s['total_pnl_pct']:+.2f}%")
        print(f"   Equity curve: {sparkline(s['equity_curve'], width=50)}")

    asyncio.run(run())


def cmd_live(args) -> None:
    import asyncio
    import os

    from apps.engine.brokers import available_brokers, get_broker
    from apps.engine.live import (
        DhanQuotePriceSource,
        KiteQuotePriceSource,
        LiveTrader,
        ReplayPriceSource,
    )
    from libs.risk.engine import RiskEngine

    if args.mode == "live" and os.environ.get("LIVE_TRADING_ENABLED", "false").lower() != "true":
        raise SystemExit("❌ LIVE trading disabled — LIVE_TRADING_ENABLED=true set karo (sirf tab jab sach mein taiyaar ho)")
    if args.mode == "live":
        print("⚠️⚠️⚠️  LIVE MODE — REAL MONEY. Kill switch hamesha tayyar rakho.")

    async def run():
        def on_event(ev):
            t = ev["type"]
            if t == "live.order":
                o = ev["order"]
                emoji = "🟢" if o["side"] == "BUY" else "🔴"
                print(f"   {emoji} ORDER [{o.get('order_id', '')[:14]}] {o['side']} {o['qty']} @ ₹{o['price']} ({o['status']})")
            elif t == "live.rejected":
                print(f"   🛡️  RISK REJECTED: {ev['reason']}")
            elif t == "live.tick" and args.verbose:
                print(f"   tick ₹{ev['price']} · equity ₹{ev['equity']:,.0f} [{ev['mode']}]")
            elif t in ("live.started", "kill", "live.finished"):
                print(f"   ▶ {t}")

        exchange, _, symbol = args.instrument.partition(":")
        # broker creds (env se) + live quote source per broker
        known = {b["name"]: b for b in available_brokers()}
        if args.broker not in known:
            raise SystemExit(f"❌ Unknown broker '{args.broker}'. Available: {', '.join(sorted(known))}")
        creds_present = all(os.environ.get(v) for v in known[args.broker]["required_env"])
        kwargs: dict = {}
        source = None
        if args.broker == "kite":
            kwargs = {"api_key": os.environ.get("KITE_API_KEY"),
                      "access_token": os.environ.get("KITE_ACCESS_TOKEN")}
            if creds_present:
                source = KiteQuotePriceSource(exchange, symbol,
                                              api_key=kwargs["api_key"],
                                              access_token=kwargs["access_token"])
        elif args.broker == "dhan":
            kwargs = {"client_id": os.environ.get("DHAN_CLIENT_ID"),
                      "access_token": os.environ.get("DHAN_ACCESS_TOKEN")}
            if creds_present:
                source = DhanQuotePriceSource(exchange, symbol,
                                              client_id=kwargs["client_id"],
                                              access_token=kwargs["access_token"])
        if source is None:
            source = ReplayPriceSource(args.instrument, speed=args.speed, limit=args.limit)
        broker = get_broker(args.broker, dry_run=(args.mode == "dry_run"), **kwargs)
        trader = LiveTrader(args.instrument, args.strategy, parse_set(args.set),
                            broker=broker, risk_engine=RiskEngine(),
                            price_source=source, on_event=on_event,
                            capital=args.capital, product=args.product,
                            trading_hours_only=(args.mode == "live"))
        await trader.start()
        if trader._task:
            await trader._task
        s = trader.state()
        print(f"\n📊 Live Trader ({s['mode']}) — {s['instrument']} · {s['strategy']}")
        print(f"   Equity: ₹{s['current_equity']:,.2f} · P&L: {s['total_pnl_pct']:+.2f}% · "
              f"Open orders: {len(s['open_orders'])}")

    asyncio.run(run())


def main() -> None:
    ap = argparse.ArgumentParser(description="AI Quant Platform — Backtest Engine CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("strategies", help="List available strategies").set_defaults(func=cmd_strategies)

    b = sub.add_parser("backtest", help="Run a backtest")
    b.add_argument("--instrument", required=True, help="e.g. NSE:TESTCO")
    b.add_argument("--strategy", required=True, choices=list(STRATEGIES.keys()))
    b.add_argument("--from", dest="start", default=None, help="YYYY-MM-DD")
    b.add_argument("--to", dest="end", default=None, help="YYYY-MM-DD")
    b.add_argument("--capital", type=float, default=1_000_000)
    b.add_argument("--set", action="append", default=None, help="strategy param, e.g. --set fast_ema=5")
    b.set_defaults(func=cmd_backtest)

    p = sub.add_parser("paper", help="Paper trading (replay mode — real prices, fake money)")
    p.add_argument("--instrument", required=True)
    p.add_argument("--strategy", default="ema_cross",
                   choices=list(STRATEGIES.keys()) + ["ai_agent"])
    p.add_argument("--capital", type=float, default=1_000_000)
    p.add_argument("--speed", type=float, default=0.5,
                   help="seconds per candle (0 = as fast as possible)")
    p.add_argument("--limit", type=int, default=150)
    p.add_argument("--set", action="append", default=None, help="strategy param, e.g. --set fast_ema=5")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_paper)

    lv = sub.add_parser("live", help="Live trading (Kite dry-run default; real only with env gates)")
    lv.add_argument("--instrument", required=True)
    lv.add_argument("--strategy", default="ema_cross", choices=list(STRATEGIES.keys()))
    lv.add_argument("--mode", choices=["dry_run", "live"], default="dry_run")
    lv.add_argument("--broker", default="kite", help="kite (Zerodha) ya dhan")
    lv.add_argument("--capital", type=float, default=1_000_000)
    lv.add_argument("--product", default="CNC", choices=["CNC", "MIS"], help="CNC=delivery (no leverage) — safe default")
    lv.add_argument("--speed", type=float, default=1.0, help="replay source speed (dry_run without kite creds)")
    lv.add_argument("--limit", type=int, default=150)
    lv.add_argument("--set", action="append", default=None, help="strategy param, e.g. --set fast_ema=5")
    lv.add_argument("--verbose", action="store_true")
    lv.set_defaults(func=cmd_live)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
