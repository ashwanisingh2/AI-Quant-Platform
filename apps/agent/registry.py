"""Signal registry — agent signals ka state (pending/approved/rejected).

MVP: in-memory + JSON files (data/agent_runs/) persist.
API approve/reject yahin karti hai; PaperTrader yahin se approved signals padhta hai.
"""
from __future__ import annotations

import json
from pathlib import Path

from libs.shared.models import AgentRun


class SignalRegistry:
    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self.runs: dict[str, dict] = {}  # run_id → run dict
        self._load()

    def _load(self):
        if not self.runs_dir.exists():
            return
        for p in self.runs_dir.glob("*.json"):
            try:
                r = json.loads(p.read_text())
                self.runs[r["id"]] = r
            except Exception:
                pass

    def add(self, run: AgentRun) -> dict:
        d = json.loads(run.model_dump_json())
        self.runs[run.id] = d
        return d

    def _update_status(self, run_id: str, status: str) -> dict:
        if run_id not in self.runs:
            raise KeyError(f"Signal nahi mili: {run_id}")
        self.runs[run_id]["final_signal"]["status"] = status
        p = self.runs_dir / f"{run_id}.json"
        if p.exists():
            p.write_text(json.dumps(self.runs[run_id], indent=2))
        return self.runs[run_id]

    def approve(self, run_id: str) -> dict:
        return self._update_status(run_id, "approved")

    def reject(self, run_id: str) -> dict:
        return self._update_status(run_id, "rejected")

    def get(self, run_id: str) -> dict | None:
        return self.runs.get(run_id)

    def list(self, limit: int = 50) -> list[dict]:
        return sorted(self.runs.values(), key=lambda r: r["created_at"], reverse=True)[:limit]

    def approved(self, instrument: str | None = None) -> list[dict]:
        """Approved signals (optionally instrument-filtered) — paper trading ke liye."""
        out = []
        for r in self.runs.values():
            sig = r["final_signal"]
            if sig["status"] != "approved":
                continue
            if instrument and r["instrument"] != instrument:
                continue
            out.append({
                "run_id": r["id"],
                "instrument": r["instrument"],
                "direction": sig["direction"],
                "confidence": sig["confidence"],
                "target_price": sig["target_price"],
                "stoploss": sig["stoploss"],
                "size_hint": sig["size_hint"],
                "reasoning": sig["reasoning"],
            })
        return out
