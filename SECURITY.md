# 🔒 Security Policy

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

This project can trade with **real money**. A security bug here can cost someone
real funds. Responsible disclosure matters.

📧 **Email:** security@ai-quant-platform.dev (or open a [private security advisory](https://github.com/ai-quant-platform/ai-quant-platform/security/advisories/new))

Please include:
- What the vulnerability is (and where — file, endpoint, CLI flag)
- Steps to reproduce
- Impact (can it cause unwanted orders? leak API keys? lose funds?)
- Suggested fix, if you have one

**Response time:** we aim to acknowledge within **48 hours** and provide a fix
or mitigation within **7 days** for critical issues.

## Scope

In scope:
- Live trading paths (`apps/engine/kite_broker.py`, `apps/engine/live.py`, `apps/api/main.py` live endpoints)
- Safety gates bypass (e.g. a way to start live trading without `LIVE_TRADING_ENABLED`)
- Kill switch not working (positions not squared off)
- Secrets handling (`.env`, Kite keys, LLM keys leaking into logs/data)
- Risk engine bypass (an order reaching the broker without checks)

Out of scope:
- Vulnerabilities in third-party dependencies (report upstream; we will upgrade)
- Issues that require physical access to the machine
- Social engineering

## Safe Harbor

We will not pursue legal action against researchers who:
- Act in good faith and avoid privacy violations, data destruction, and service interruption
- Do not trade with real money while testing
- Give us reasonable time to fix before public disclosure

## Security Best Practices for Users

See [SAFETY.md](SAFETY.md) — read it **before** enabling live trading.

Key points:
- Never commit `.env` (it is git-ignored — keep it that way)
- `LIVE_TRADING_ENABLED` stays `false` until you are ready
- Max capital limit (`LIVE_MAX_CAPITAL`) is your seatbelt — use it
- Kill switch (`POST /kill-switch`) must always work — test it in dry-run first

API access is protected by a single operator bearer token; see README.md for setup,
rotation, HTTPS deployment, WebSocket authentication and remaining limitations.
