"""Phase 2 demo: AI agent pipeline (Analyst → Trader → Risk) on TESTCO + INFY.

Mock LLM use karta hai — bina API key ke. Real LLM ke liye:
  pip install litellm
  export LLM_MODEL="gemini/gemini-2.0-flash"
  export LLM_API_KEY="..."
  python -m apps.agent.main analyze --instrument NSE:TESTCO --llm auto

Run:  python scripts/demo_phase2.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root

from apps.agent.analysis import build_snapshot
from apps.agent.graph.pipeline import run_pipeline
from apps.agent.llm.mock_llm import MockLLMClient
from apps.agent.main import print_signal_card, save_run
from libs.shared.models import PortfolioState
from libs.storage.parquet_store import ParquetStore


def main() -> None:
    print("=" * 74)
    print("🧠 Phase 2 Demo — AI Agent Pipeline (Analyst → Trader → Risk)")
    print("   LLM: mock (deterministic, no API key) — real ke liye env vars set karo")
    print("=" * 74)

    store = ParquetStore()
    for instrument in ["NSE:TESTCO", "NSE:INFY"]:
        candles = store.read_candles(instrument)
        if len(candles) < 30:
            print(f"\n⚠️  {instrument}: data kam hai ({len(candles)} candles) — skip")
            continue
        snapshot = build_snapshot(instrument, candles)
        portfolio = PortfolioState(cash=1_000_000, total_value=1_000_000)
        run = run_pipeline(snapshot, portfolio, "ai_agent_v1", {}, MockLLMClient())
        save_run(run)
        print_signal_card(run)

    print("\n" + "=" * 74)
    print("✅ Phase 2 complete! AI agent pipeline WORKING (mock LLM).")
    print("   Real LLM plug karo: pip install litellm + LLM_MODEL/LLM_API_KEY env → --llm auto")
    print("   Next: Phase 3 — Dashboard + paper trading")
    print("=" * 74)


if __name__ == "__main__":
    main()
