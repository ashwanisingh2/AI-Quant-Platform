# 🛡️ SAFETY.md — Live Trading Se Pehle Ye Padho

> ⚠️ **Ye platform REAL MONEY se trade kar sakta hai.**
> Neeche wali checklist bina complete kiye **live mode mat kholo**.

---

## 1️⃣ Kabhi nahi bhulna

- [ ] **Pehle 2-3 mahine paper/dry-run trading** — bina exception ke. Strategy ka behaviour, slippage, aur apne emotions samajhne ke liye.
- [ ] **Sirf woh paisa lagao jo kho sakte ho** — chhota capital se start karo (default cap ₹50,000).
- [ ] **CNC (delivery) se start karo** — MIS/intraday aur F&O baad mein, samajh ke.
- [ ] **Kill switch hamesha tayyar rakho** — dashboard ka red button ya `POST /kill-switch`. Ek click → sab band, saari positions square off.
- [ ] **Market hours mein hi live run karo** — engine IST 09:15–15:30 Mon–Fri enforce karta hai.
- [ ] **Daily loss limit set rakho** — default −3% per day. Uske neeche aaj ke liye band.

## 2️⃣ Live mode kaise enable karein (4 gates)

```bash
export LIVE_TRADING_ENABLED=true          # gate 1: samajh-bujh ke
                                           # gate 2: API/CLI se exact phrase:
                                           #   "I UNDERSTAND THIS TRADES REAL MONEY"
export LIVE_MAX_CAPITAL=50000              # gate 3: apni max limit (₹)

# gate 4: broker creds — apne broker ke hisaab se:
export KITE_API_KEY="your_key"             # Zerodha Kite
export KITE_ACCESS_TOKEN="your_token"
# YA
export DHAN_CLIENT_ID="your_client_id"     # Dhan
export DHAN_ACCESS_TOKEN="your_token"
```

Bina inke live start nahi hoga — engine 400 error dega. Ye jaan-bujhkar rakha gaya hai.

## 3️⃣ Broker setup (Kite ya Dhan)

**Zerodha Kite:**
1. [Kite Connect](https://kite.trade/) pe account banao (developer console).
2. `KITE_API_KEY` lo. Access token ke liye pehli baar login flow (request token → session) karna padta hai — [Kite docs](https://kite.trade/docs/connect/v3/#authentication).
3. **Sandbox/testnet nahi hai Kite ka** — dry-run hamara apna simulated broker hai (`KiteBroker(dry_run=True)`).

**Dhan:**
1. [DhanHQ](https://dhanhq.co/) pe developer account banao.
2. `DHAN_CLIENT_ID` + `DHAN_ACCESS_TOKEN` lo (access token daily regenerate hota hai).
3. Yaad rakho — Dhan ki baatein alag hain: security_id (e.g. `1333` = HDFC Bank), segments `NSE_EQ`, product `CNC`/`INTRA`. Hamara adapter (`DhanBroker`) ye sab handle karta hai.
4. `GET /brokers` se dekh sakte ho kaun-kaun se brokers hain aur creds hain ya nahi.

**Upstox:**
1. [Upstox Developer](https://upstox.com/developer/) pe app banao.
2. `UPSTOX_API_KEY` + `UPSTOX_ACCESS_TOKEN` lo (login flow ke baad access token milta hai).
3. Yaad rakho — Upstox ki baatein alag hain: instrument key `NSE_EQ|ISIN`, products `D` (delivery) / `I` (intraday). Hamara adapter (`UpstoxBroker`) ye sab handle karta hai.

**Fyers:**
1. [Fyers API](https://myapi.fyers.in/) pe app banao.
2. `FYERS_CLIENT_ID` (e.g. `AB12345-100`) + `FYERS_ACCESS_TOKEN` lo.
3. Yaad rakho — Fyers ke symbols `NSE:SBIN-EQ` format mein hote hain, aur order side/type **numbers** mein (1=BUY, 2=MARKET). Hamara adapter (`FyersBroker`) ye sab handle karta hai.

**Koi bhi broker ho — same safety:** risk engine ke 11 checks, kill switch, aur 4 gates sab par lagte hain. `GET /brokers` se dekh sakte ho kaun-kaun se hain aur creds hain ya nahi.

## 4️⃣ Pehla live run — chhota aur dhyaan se

```bash
# Step 1: dry-run (bina paisa lagaye, live jaisa)
python -m apps.engine.main live --instrument NSE:TESTCO --strategy ema_cross --mode dry_run

# Step 2: API se status dekho
curl localhost:8000/live/status

# Step 3: jab 100% sure ho → live (chhote capital se)
# dashboard ya API: POST /live/start {"mode": "live", "capital": 50000, "confirm": "..."}
```

- Pehla din **1 instrument, chhoti quantity** se dekho.
- Broker app (Kite/Zerodha) mein positions **double-check** karo — hamari reconciliation startup pe hoti hai, phir bhi.
- End of day: `POST /kill-switch` → sab square off.

## 5️⃣ Risk Engine — kya-kya rokega (bina tere kuch kiye)

| Rule | Default | Matlab |
|---|---|---|
| Kill switch | hamesha | ek click → sab band |
| Trading hours | IST 09:15–15:30, Mon–Fri | iske bahar order nahi |
| Position cap | 20% capital ya ₹2L (jo kam ho) | ek instrument mein zyada nahi |
| Max positions | 5 | concentration kam |
| Daily loss | −3% | din ka loss limit |
| Max drawdown | −10% | overall protection |
| AI confidence | ≥0.6 | kam confidence → reject |
| Rate limit | 5 orders/min | glitch/loop se bachao |
| Price deviation | ≤10% vs reference | circuit/ freak trade se bachao |

Har order ka **audit trail** banta hai — kaunsa check pass/fail hua, sab recorded.

## 6️⃣ Agar kuch galat ho

1. **Kill switch immediately** — `POST /kill-switch` ya dashboard button.
2. Broker app mein jaakar dekho — kya saari positions square off hui hain.
3. Agar nahi hui → manually close karo broker se.
4. Logs dekho: `data/agent_runs/`, API console, `live.rejected` events (risk ne kya roka).

## 7️⃣ Galatiyon se bachne ke tips

- **Kabhi bhi `--mode live` apne laptop pe unattended mat chhodo.**
- **VPN/proxy ke peeche mat chalao** — Kite API IP-sensitive ho sakti hai.
- **Access token expire hota hai** — roz naya login flow.
- **MIS mat use karo jab tak samajh na aa jaye** — overnight positions ka risk alag hai.
- **F&O bilkul nahi** — yeh MVP sirf equity delivery (CNC) ke liye hai.

---

> 🚨 **Yaad rakho:** Stock market mein paisa banana mushkil hai, aur **jaldi kho dena aasaan**. Ye platform tools hain — zimmedari teri hai. Ye financial advice nahi hai.
