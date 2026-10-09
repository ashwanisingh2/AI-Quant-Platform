"""Phase 0 end-to-end demo: FETCH → STORE → QUERY.

Run:  python scripts/demo_phase0.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root

from apps.data_gateway.providers.mock_provider import MockProvider
from libs.shared.charts import sparkline
from libs.storage.parquet_store import ParquetStore


def main() -> None:
    print("=" * 62)
    print("🚀 Phase 0 Demo — AI Quant Platform: Data Foundation")
    print("=" * 62)

    store = ParquetStore()

    # 1. FETCH (mock — deterministic, no internet needed)
    print("\n[1/4] Fetching 120 days of MOCK data for NSE:TESTCO ...")
    provider = MockProvider(seed=42)
    candles = provider.get_historical("TESTCO", days=120)
    print(f"      got {len(candles)} daily candles "
          f"({candles[0].timestamp.date()} → {candles[-1].timestamp.date()})")

    # 2. STORE
    print("\n[2/4] Storing to Parquet (data/ohlcv/NSE_TESTCO/) ...")
    n = store.write_candles(candles)
    print(f"      wrote {n} candles")

    # 3. QUERY (read back + summary + sparkline)
    print("\n[3/4] Reading back from storage ...")
    back = store.read_candles("NSE:TESTCO")
    s = store.summary("NSE:TESTCO")
    print(f"      read {len(back)} candles back ✅")
    print(f"      summary: {s}")
    print(f"\n      Last 30 closes: {sparkline([c.close for c in back[-30:]])}")
    print(f"      Last candle: close ₹{back[-1].close} "
          f"(low ₹{back[-1].low} / high ₹{back[-1].high})")

    # 4. REAL NSE data (bhavcopy — no API key needed)
    print("\n[4/4] Trying REAL NSE data (bhavcopy, last 5 trading days, RELIANCE) ...")
    try:
        from apps.data_gateway.providers.bhavcopy_provider import BhavcopyProvider
        real = BhavcopyProvider().get_historical("RELIANCE", days=5)
        if real:
            store.write_candles(real)
            print(f"      ✅ REAL data stored: {len(real)} days, "
                  f"last close ₹{real[-1].close} ({real[-1].timestamp.date()})")
        else:
            print("      ⚠️  NSE se download nahi hua (blocked/NA) — mock data se kaam chalta rahega")
    except Exception as e:
        print(f"      ⚠️  skipped ({type(e).__name__}: {e})")

    print("\n" + "=" * 62)
    print("✅ Phase 0 complete! Pipeline: fetch → store → query WORKING.")
    print("   Next: Phase 1 — Backtest engine (NautilusTrader)")
    print("=" * 62)


if __name__ == "__main__":
    main()
