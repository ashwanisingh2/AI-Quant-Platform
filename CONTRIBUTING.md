# 🤝 Contributing to AI Quant Platform

Pehla baari? Welcome! 🎉 Ye project India-first trading platform hai — contributions
bade pyare hain, chahe woh ek typo fix ho ya ek nayi strategy.

> ⚠️ **Sabse pehle:** [SAFETY.md](SAFETY.md) padho. Agar aapka change live trading
> ko touch karta hai, toh safety pe extra dhyaan.

## Quick Start

```bash
git clone <repo-url>
cd ai-quant-platform
pip install -e ".[all,dev]"        # sab kuch: package + llm + kite + dev tools
cd apps/dashboard && npm install   # dashboard ke liye
```

## Development Workflow

1. **Fork** → **branch** (`git checkout -b feature/tera-naam`)
2. **Code** — neeche dekho "coding style"
3. **Test** — `python scripts/test_all.py` (40 tests; API/dashboard wale ke liye servers chahiye)
4. **Lint** — `ruff check .`
5. **PR** — template fill karo, description mein "kya aur kyun" likho

## Test Pehle, Code Baad (ya saath mein)

Har naye feature ke saath test add karo (`scripts/test_all.py` mein). CI mein yeh
sab chalega — agar test fail toh merge nahi hoga.

```bash
# Servers chala ke full suite
python -m apps.api.main &                     # port 8000
cd apps/dashboard && npm run dev &            # port 5173
python scripts/test_all.py
```

## Coding Style

- **Python:** ruff (`ruff check .`), line-length 100, type hints (`from __future__ import annotations`)
- **Hinglish allowed** — comments/messages mein Hinglish bilkul chalta hai 😄
- **Naming:** `snake_case` functions/variables, `PascalCase` classes
- **Safety first:** live-trading code mein koi bhi change → 2 baar socho, test karo, SAFETY.md dekho

## What to Contribute

- 🐛 Bug fixes (label: `bug`)
- 📈 Nayi strategies (`apps/engine/strategies/`)
- 🧠 AI prompts (`libs/prompts/v1/`)
- 🌐 Brokers (Dhan/Upstox/Fyers — Phase 6+)
- 📊 Dashboard features
- 📚 Docs, examples, demos
- 🧪 Tests (hamesha welcome!)

## Commit Messages

Clear aur chhote:

```
feat: rsi strategy add ki
fix: kill switch positions close nahi kar raha tha
test: risk engine rate limit test
chore: docker compose healthcheck
```

## Code of Conduct

[Same as everyone else](CODE_OF_CONDUCT.md) — respect, no harassment, constructive feedback.

## Questions?

GitHub Discussions ya issue mein poochho — koi bhi question chhota nahi hota.

Happy hacking! 🚀📈
