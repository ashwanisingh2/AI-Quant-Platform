"""Data Gateway CLI — fetch / list / show.

Usage:
  python -m apps.data_gateway.main fetch --provider mock --symbol TESTCO --days 120
  python -m apps.data_gateway.main fetch --provider bhavcopy --symbol RELIANCE --days 30
  python -m apps.data_gateway.main fetch --provider kite --symbol RELIANCE --days 30
  python -m apps.data_gateway.main list
  python -m apps.data_gateway.main show --instrument NSE:RELIANCE --spark
"""
from __future__ import annotations

import argparse
import os
from datetime import date

from libs.shared.charts import sparkline
from libs.storage.parquet_store import ParquetStore, instrument_from_dir


def get_provider(name: str):
    if name == "mock":
        from apps.data_gateway.providers.mock_provider import MockProvider
        return MockProvider()
    if name == "bhavcopy":
        from apps.data_gateway.providers.bhavcopy_provider import BhavcopyProvider
        return BhavcopyProvider()
    if name == "kite":
        from apps.data_gateway.providers.kite_provider import KiteProvider
        api_key = os.environ.get("KITE_API_KEY")
        if not api_key:
            raise SystemExit("❌ KITE_API_KEY env variable set karo (Kite Connect account se)")
        return KiteProvider(
            api_key=api_key,
            access_token=os.environ.get("KITE_ACCESS_TOKEN"),
        )
    raise SystemExit(f"❌ Unknown provider: {name} (use: mock | bhavcopy | kite)")


def cmd_fetch(args) -> None:
    provider = get_provider(args.provider)
    candles = provider.get_historical(args.symbol, days=args.days, exchange=args.exchange)
    if not candles:
        raise SystemExit(f"❌ No data for {args.exchange}:{args.symbol} from '{args.provider}'")
    store = ParquetStore()
    store.write_candles(candles)
    print(f"✅ [{provider.name}] {args.exchange}:{args.symbol}: {len(candles)} candles fetched & stored")
    print(f"   range: {candles[0].timestamp.date()} → {candles[-1].timestamp.date()}")
    print(f"   last close: ₹{candles[-1].close}")


def cmd_list(args) -> None:
    store = ParquetStore()
    instruments = store.list_instruments()
    if not instruments:
        print("📭 No data stored yet. Pehle ek 'fetch' command run karo.")
        return
    print(f"{'INSTRUMENT':<20} {'CANDLES':>8}  {'FROM':<12} {'TO':<12} {'LAST CLOSE':>12}")
    for inst in instruments:
        inst_key = instrument_from_dir(inst)
        s = store.summary(inst_key)
        if s:
            print(f"{inst_key:<20} {s['candles']:>8}  {s['from']:<12} {s['to']:<12} {s['last_close']:>12.2f}")


def cmd_show(args) -> None:
    store = ParquetStore()
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    candles = store.read_candles(args.instrument, start=start, end=end)
    if not candles:
        raise SystemExit(f"❌ No data for {args.instrument}")
    print(f"📈 {args.instrument} — {len(candles)} candles stored")
    print(f"{'DATE':<12} {'OPEN':>10} {'HIGH':>10} {'LOW':>10} {'CLOSE':>10} {'VOLUME':>12}")
    for c in candles[-args.tail:]:
        print(f"{str(c.timestamp.date()):<12} {c.open:>10.2f} {c.high:>10.2f} "
              f"{c.low:>10.2f} {c.close:>10.2f} {c.volume:>12,}")
    if args.spark:
        print(f"\nSparkline (last {len(candles)} closes):")
        print(sparkline([c.close for c in candles]))


def main() -> None:
    ap = argparse.ArgumentParser(description="AI Quant Platform — Data Gateway CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="Fetch data from a provider and store it")
    f.add_argument("--provider", default="mock", choices=["mock", "bhavcopy", "kite"])
    f.add_argument("--symbol", required=True)
    f.add_argument("--exchange", default="NSE")
    f.add_argument("--days", type=int, default=60)
    f.set_defaults(func=cmd_fetch)

    lst = sub.add_parser("list", help="List stored instruments")
    lst.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="Show stored candles")
    s.add_argument("--instrument", required=True, help="e.g. NSE:RELIANCE")
    s.add_argument("--start", default=None, help="YYYY-MM-DD")
    s.add_argument("--end", default=None, help="YYYY-MM-DD")
    s.add_argument("--tail", type=int, default=10)
    s.add_argument("--spark", action="store_true")
    s.set_defaults(func=cmd_show)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
