# Capability and upstream matrix

| Area | V2 state | Remaining work |
|---|---|---|
| Shared strategy decisions | Implemented, replay-tested | Bar cadence and live fill parity |
| Durable API execution sessions | SQLite run/intent journal | CLI coverage, backup automation, HA |
| Recovery | Manual broker verification gate | Automated broker reconciliation |
| Backtests | Data hash, signal trace, benchmark, estimated costs | Walk-forward, point-in-time datasets, market-specific fees |
| AI research | Linear analyst/trader/risk pipeline | Specialist debate, source citations, calibration |
| Broker adapters | Kite/Dhan/Upstox/Fyers code and dry-run tests | Broker-by-broker live certification |
| F&O chain | Synthetic sandbox | Licensed real option chain and verified contracts |
| Authentication | Single private operator token | User accounts, RBAC, broker OAuth renewal |
| Dashboard | Unified responsive workspace | Long-duration browser and accessibility audits |

## Upstream roles

| Project | Proposed role | Integration status |
|---|---|---|
| NautilusTrader | Backtest/runtime engine | Backtest dependency; custom live orchestration remains |
| Backtrader | Strategy compatibility reference | Not integrated |
| TradingAgents | Multi-agent research reference | Not integrated |
| TradingAgents-CN | Localized research workflows | Not integrated |
| FinceptTerminal | Research workspace reference | Not integrated |
| Vibe-Trading | Research tool orchestration reference | Not integrated |
| CCXT | Optional crypto connectivity | Not integrated; current scope is Indian brokers |
| vn.py | Gateway/event architecture reference | Not integrated |
| Freqtrade | Validation and strategy workflow reference | Not integrated |

Do not describe a reference as an installed dependency. Before incorporating any
upstream implementation, record its pinned revision, applicable license, attribution
and interface ownership. This release adds no code copied from these references.
