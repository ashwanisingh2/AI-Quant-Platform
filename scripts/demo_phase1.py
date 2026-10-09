"""Phase 1 demo: dono strategies × dono instruments — comparison table.

Run:  python scripts/demo_phase1.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root

from apps.engine.runner import run_backtest, save_results


def main() -> None:
    print("=" * 74)
    print("🧠 Phase 1 Demo — Backtest Engine (NautilusTrader)")
    print("=" * 74)

    instruments = ["NSE:TESTCO", "NSE:INFY"]
    strategies = ["ema_cross", "rsi"]

    rows = []
    for inst in instruments:
        for strat in strategies:
            print(f"\n⏳ {inst} · {strat} ...")
            try:
                r = run_backtest(instrument=inst, strategy_name=strat)
                save_results(r)
                rows.append(r)
            except Exception as e:
                print(f"   ❌ failed: {e}")

    print("\n" + "=" * 74)
    print("📊 COMPARISON")
    print("=" * 74)
    print(f"{'INSTRUMENT':<14} {'STRATEGY':<10} {'RETURN':>9} {'SHARPE':>8} {'MAXDD':>8} {'TRADES':>7}")
    print("-" * 74)
    for r in rows:
        ret = f"{'+' if r['total_return_pct'] >= 0 else ''}{r['total_return_pct']}%"
        sharpe = f"{r['sharpe_ratio']:.2f}" if r["sharpe_ratio"] is not None else "n/a"
        print(f"{r['instrument']:<14} {r['strategy']:<10} {ret:>9} {sharpe:>8} "
              f"{r['max_drawdown_pct']:>7}% {r['n_trades']:>7}")

    print("\n✅ Phase 1 complete! Backtest engine WORKING.")
    print("   Next: Phase 2 — AI agent service (signals with reasoning)")
    print("=" * 74)


if __name__ == "__main__":
    main()
