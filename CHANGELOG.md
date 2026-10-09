# Changelog

## 2.0.0a1 — V2 foundation

- Responsive command center, research/execution navigation, explicit capability boundaries.
- Shared EMA/RSI decision kernel across Nautilus backtesting, paper and live adapters.
- Backtest data fingerprints, decision traces, benchmark and estimated turnover costs.
- Persistent API execution sessions and pre-submission order intents in SQLite.
- Unknown-outcome handling and manual reconciliation before another live session.
- Recovery screen, fault-tolerant status, API validation and authenticated event handshake.
- Includes private dev credentials, partial kill-switch reporting and loop-crash fixes.
- Architecture decisions, capability matrix, operator runbook and V2 regression tests.

Breaking behavior: live sessions require reconciliation before reuse; backtest
signals use the shared kernel (RSI uses 0–100 values). Historical V1 results may differ.
