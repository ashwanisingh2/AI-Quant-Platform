"""Backtest runner — Nautilus engine setup + run + results.

Yeh Phase 1 ka dil hai: strategy ko historical data pe chala ke
returns, Sharpe, drawdown, equity curve nikalta hai.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
import warnings
from datetime import date, datetime, timezone
from pathlib import Path

from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import INR
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

from apps.engine.data_loader import load_bars, parse_instrument
from apps.engine.strategies import STRATEGIES

warnings.filterwarnings("ignore", message="Timestamp.utcnow is deprecated")

RESULTS_DIR = Path(__file__).resolve().parents[2] / "data" / "backtests"


def _clean(v):
    """NaN/inf → None (JSON-safe)."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _max_drawdown_pct(curve: list[float]) -> float:
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak * 100)
    return round(mdd, 2)


def compute_equity_curve(bars, fills_df, initial_capital: float) -> list[float]:
    """Fills + bar closes se equity curve banata hai (mark-to-market)."""
    fills = []
    if len(fills_df):
        for _, r in fills_df.iterrows():
            ts = int(r["ts_init"].value)  # ns
            is_buy = "BUY" in str(r["side"]).upper()
            fills.append((ts, is_buy, float(r["quantity"]), float(r["avg_px"])))
    fills.sort()

    cash = initial_capital
    pos = 0.0
    curve: list[float] = []
    i = 0
    for bar in bars:
        while i < len(fills) and fills[i][0] <= bar.ts_event:
            _, is_buy, qty, px = fills[i]
            if is_buy:
                cash -= qty * px
                pos += qty
            else:
                cash += qty * px
                pos -= qty
            i += 1
        curve.append(cash + pos * bar.close.as_double())
    return curve


def run_backtest(
    instrument: str,
    strategy_name: str,
    params: dict | None = None,
    start: date | None = None,
    end: date | None = None,
    capital: float = 1_000_000,
    cost_bps: float = 0.0,
) -> dict:
    """Ek backtest chalao aur results dict return karo."""
    if not math.isfinite(capital) or capital <= 0 or not math.isfinite(cost_bps) or not 0 <= cost_bps <= 1000:
        raise ValueError('Positive capital and cost_bps between 0 and 1000 required')
    spec = STRATEGIES[strategy_name]
    params = {**spec["defaults"], **(params or {})}

    nautilus_instrument, bar_type, bars = load_bars(instrument, start=start, end=end)
    config = spec["config"](instrument_id=nautilus_instrument.id, bar_type=bar_type, **params)
    strategy = spec["class"](config)

    engine = BacktestEngine(config=BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
    engine.add_venue(
        venue=Venue(parse_instrument(instrument)[0]),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money(int(capital), INR)],
        base_currency=INR,
    )
    engine.add_instrument(nautilus_instrument)
    engine.add_data(bars)
    engine.add_strategy(strategy)
    engine.run()

    fills_df = engine.trader.generate_order_fills_report()
    stats_returns = {k: _clean(v) for k, v in engine.portfolio.analyzer.get_performance_stats_returns().items()}
    stats_general = {k: _clean(v) for k, v in engine.portfolio.analyzer.get_performance_stats_general().items()}

    equity_curve = compute_equity_curve(bars, fills_df, capital)
    final_equity = equity_curve[-1] if equity_curve else capital

    # Transparent post-fill cost estimate, not a broker-specific tax/fill model.
    turnover = sum(abs(float(r['quantity']) * float(r['avg_px'])) for _, r in fills_df.iterrows()) if len(fills_df) else 0.0
    estimated_cost = turnover * cost_bps / 10000
    digest = hashlib.sha256('\n'.join(str(b) for b in bars).encode()).hexdigest()
    start_dt = datetime.fromtimestamp(bars[0].ts_event / 1e9, tz=timezone.utc).date()
    end_dt = datetime.fromtimestamp(bars[-1].ts_event / 1e9, tz=timezone.utc).date()

    return {
        "run_id": uuid.uuid4().hex,
        "kernel_version": "2.0.0",
        "data_sha256": digest,
        "signal_trace": strategy.signal_trace,
        "cost_model": {"kind": "post_fill_turnover_bps", "bps": cost_bps},
        "estimated_cost_inr": round(estimated_cost, 2),
        "net_return_pct": round((final_equity - estimated_cost - capital) / capital * 100, 2),
        "benchmark_return_pct": round((bars[-1].close.as_double() / bars[0].close.as_double() - 1) * 100, 2),
        "validation": "in_sample_only",
        "instrument": instrument,
        "strategy": strategy_name,
        "params": params,
        "start": str(start_dt),
        "end": str(end_dt),
        "days": len(bars),
        "initial_capital": capital,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round((final_equity / capital - 1) * 100, 2),
        "max_drawdown_pct": _max_drawdown_pct([capital, *equity_curve]),
        "sharpe_ratio": stats_returns.get("Sharpe Ratio (252 days)"),
        "n_trades": int(len(fills_df)),
        "win_rate_pct": stats_general.get("Win rate [%]"),
        "stats_returns": stats_returns,
        "stats_general": stats_general,
        "equity_curve": [round(v, 2) for v in equity_curve],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def save_results(results: dict) -> Path:
    """Results ko JSON mein save karo (baad mein dashboard ke liye)."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    inst = results["instrument"].replace(":", "_")
    path = RESULTS_DIR / f"{inst}_{results['strategy']}_{ts}_{results.get('run_id', uuid.uuid4().hex)}.json"
    path.write_text(json.dumps(results, indent=2))
    return path
