# Changelog

## Unreleased

- Kotak Neo log redaction now fully masks values the SDK only partially masks or leaves
  in plain text: MPIN and TOTP (`65***21` leaked 4 of 6 digits on failed-login ERROR logs),
  session token, `sid`/`rid`, PAN (`kId`), account name, and truncated response previews.
- SDK log file directory `logs/` is ignored by git and excluded from Docker builds.
- Operations runbook: Kotak order outcomes, OPS guard, session expiry, kill-switch
  reporting and SDK logging guidance.

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
