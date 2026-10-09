import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { apiGet, apiPost } from '../api'

const CONFIRM_PHRASE = 'I UNDERSTAND THIS TRADES REAL MONEY'

export default function Live() {
  const [status, setStatus] = useState(null)
  const [brokers, setBrokers] = useState([])
  const [instruments, setInstruments] = useState([])
  const [strategies, setStrategies] = useState({})
  const [health, setHealth] = useState(null)
  const [form, setForm] = useState({
    broker: 'kite', mode: 'dry_run', instrument: 'NSE:TESTCO', strategy: 'ema_cross',
    capital: 1000000, speed: 1, limit: 150, product: 'CNC', confirm: '',
  })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const chartBoxRef = useRef(null)
  const seriesRef = useRef(null)
  const curveLenRef = useRef(0)

  const load = async () => {
    try {
      setStatus(await apiGet('/live/status'))
      const b = await apiGet('/brokers')
      setBrokers(b.brokers || [])
      setHealth(await apiGet('/health'))
      setInstruments((await apiGet('/instruments')).instruments)
      setStrategies((await apiGet('/strategies')).strategies)
    } catch (e) { /* API down — silently retry */ }
  }

  useEffect(() => {
    load()
    const onWs = () => load()
    window.addEventListener('ws-event', onWs)
    const iv = setInterval(load, 2000)
    return () => { window.removeEventListener('ws-event', onWs); clearInterval(iv) }
  }, [])

  // equity chart
  useEffect(() => {
    const curve = status?.equity_curve || []
    if (!curve.length || !chartBoxRef.current) return
    if (!seriesRef.current) {
      const chart = createChart(chartBoxRef.current, {
        width: chartBoxRef.current.clientWidth,
        height: 200,
        layout: { background: { color: 'transparent' }, textColor: '#8b949e' },
        grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
        rightPriceScale: { borderColor: '#30363d' },
        timeScale: { borderColor: '#30363d', timeVisible: false, secondsVisible: false },
      })
      seriesRef.current = chart.addLineSeries({ color: '#58a6ff', lineWidth: 2 })
      chartBoxRef.current._chart = chart
    }
    if (curve.length !== curveLenRef.current) {
      const now = Math.floor(Date.now() / 1000)
      seriesRef.current.setData(curve.map((v, i) => ({ time: now - (curve.length - i), value: v })))
      curveLenRef.current = curve.length
    }
  }, [status?.equity_curve?.length])

  const start = async () => {
    setBusy(true); setMsg(null)
    try {
      await apiPost('/live/start', {
        ...form,
        capital: Number(form.capital),
        speed: Number(form.speed),
        limit: Number(form.limit),
      })
    } catch (e) { setMsg(String(e.message || e)) }
    setBusy(false); load()
  }
  const stop = async () => { await apiPost('/live/stop'); load() }
  const kill = async () => {
    if (!confirm('🚨 KILL SWITCH — live + paper sab band, saari positions square off. Sure?')) return
    try {
      const result = await apiPost('/kill-switch')
      setMsg(result.manual_action_required
        ? 'Trading stopped, but broker exits/cancellations are unconfirmed. Check your broker account immediately.'
        : 'Trading stopped. Review your broker account to verify positions.')
    } catch { setMsg('Kill request failed. Check and close positions directly with your broker.') }
    load()
  }

  const running = status?.running
  const liveEnabled = health?.live_trading_enabled === true
  const pnl = status?.total_pnl_pct ?? 0
  const isLiveMode = form.mode === 'live'
  const fmt = (v) => (v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })

  return (
    <div>
      <div className="grid">
        <div className="stat"><div className="label">Equity</div><div className="value mono">₹{fmt(status?.current_equity)}</div></div>
        <div className="stat"><div className="label">Cash</div><div className="value mono">₹{fmt(status?.cash)}</div></div>
        <div className="stat"><div className="label">P&L</div><div className={`value mono ${pnl >= 0 ? 'pos' : 'neg'}`}>{pnl >= 0 ? '+' : ''}{pnl}%</div></div>
        <div className="stat"><div className="label">Mode</div><div className="value">{status?.mode ?? '—'}</div></div>
        <div className="stat"><div className="label">Status</div><div className="value">{status?.last_error ? '🔴 ERROR — STOPPED' : running ? '🟢 RUNNING' : status?.killed ? '🚨 KILLED' : '⚪ IDLE'}</div></div>
      </div>

      {status?.last_error && <p role="alert">{status.last_error.message}</p>}
      {status?.kill_result?.manual_action_required && <p role="alert">
        Emergency exit incomplete or unconfirmed. Check broker orders and positions immediately.
      </p>}
      {status?.portfolio_available === false && <p role="alert">Broker portfolio unavailable. Displayed balances cannot be verified.</p>}
      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3>🚨 Emergency</h3>
          <button className="btn kill" onClick={kill}>KILL SWITCH</button>
        </div>
        <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
          Trading turant stop hoti hai; broker orders cancel aur positions close karne ki koshish hoti hai. Result aur broker account verify karo.
        </p>
      </div>

      <div className="card">
        <h3>🟢 Live Trading {running && <span className="badge buy">running</span>}</h3>
        <div className="form-row">
          <div>
            <label>Broker</label>
            <select value={form.broker} onChange={(e) => setForm({ ...form, broker: e.target.value })}>
              {brokers.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name} {b.credentials_present ? '🔑' : '(no creds → replay)'}
                </option>
              ))}
              {brokers.length === 0 && <option value="kite">kite</option>}
            </select>
          </div>
          <div>
            <label>Mode</label>
            <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
              <option value="dry_run">dry_run (simulated — SAFE)</option>
              <option value="live" disabled={!liveEnabled}>live (REAL MONEY ⚠️)</option>
            </select>
          </div>
          <div>
            <label>Instrument</label>
            <select value={form.instrument} onChange={(e) => setForm({ ...form, instrument: e.target.value })}>
              {instruments.map((i) => <option key={i.instrument} value={i.instrument}>{i.instrument} ({i.candles})</option>)}
              {instruments.length === 0 && <option>NSE:TESTCO</option>}
            </select>
          </div>
          <div>
            <label>Strategy</label>
            <select value={form.strategy} onChange={(e) => setForm({ ...form, strategy: e.target.value })}>
              {Object.keys(strategies).map((s) => <option key={s} value={s}>{s}</option>)}
              <option value="ai_agent">ai_agent (approved signals)</option>
            </select>
          </div>
        </div>
        <div className="form-row">
          <div><label>Capital (₹)</label><input type="number" value={form.capital} onChange={(e) => setForm({ ...form, capital: e.target.value })} /></div>
          <div><label>Speed (sec)</label><input type="number" step="0.1" value={form.speed} onChange={(e) => setForm({ ...form, speed: e.target.value })} /></div>
          <div><label>Limit (candles)</label><input type="number" value={form.limit} onChange={(e) => setForm({ ...form, limit: e.target.value })} /></div>
          <div>
            <label>Product</label>
            <select value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })}>
              <option value="CNC">CNC (delivery — no leverage)</option>
              <option value="MIS">MIS (intraday ⚠️)</option>
            </select>
          </div>
          <div>
            {!running
              ? <button className="btn green" disabled={busy} onClick={start}>▶ Start</button>
              : <button className="btn red" onClick={stop}>■ Stop</button>}
          </div>
        </div>

        {isLiveMode && (
          <div className="card" style={{ borderColor: '#f85149', marginTop: 10 }}>
            <h3>⚠️⚠️⚠️ REAL MONEY — 4 safety gates</h3>
            <p className="muted" style={{ fontSize: 12 }}>
              Live mode = real orders on <b>{form.broker}</b>. Confirm phrase exact likho:
            </p>
            <div className="form-row">
              <div style={{ flex: 1 }}>
                <label>Confirm phrase</label>
                <input type="text" placeholder={CONFIRM_PHRASE} value={form.confirm}
                  onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
              </div>
            </div>
            <p className="muted" style={{ fontSize: 12 }}>
              Gates: LIVE_TRADING_ENABLED=true · max capital ₹{(health?.live_max_capital ?? 50000).toLocaleString('en-IN')}
              · broker creds · risk engine (11 checks) · kill switch. Pehle SAFETY.md padho!
            </p>
          </div>
        )}

        {!isLiveMode && (
          <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
            dry_run = real prices + simulated orders — bina paisa lagaye live jaisa.
            Har order risk engine (11 checks) se hokar guzarta hai.
          </p>
        )}
        {msg && <p style={{ color: '#f85149', fontSize: 13, marginTop: 8 }}>{msg}</p>}
      </div>

      <div className="card">
        <h3>📈 Equity Curve</h3>
        {(status?.equity_curve?.length ?? 0) > 0
          ? <div className="chart-box" ref={chartBoxRef} />
          : <p className="muted">Abhi koi data nahi — live trading start karo.</p>}
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="card">
          <h3>📦 Positions</h3>
          <table>
            <thead><tr><th>Symbol</th><th>Qty</th><th>Avg Price</th></tr></thead>
            <tbody>
              {(status?.positions || []).filter((p) => p.qty !== 0).map((p) => (
                <tr key={p.symbol}>
                  <td className="mono">{p.symbol}</td>
                  <td className="mono">{p.qty}</td>
                  <td className="mono">₹{(p.avg_price ?? 0).toFixed(2)}</td>
                </tr>
              ))}
              {(status?.positions || []).filter((p) => p.qty !== 0).length === 0 &&
                <tr><td colSpan={3} className="muted">Koi open position nahi</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>🧾 Open Orders</h3>
          <table>
            <thead><tr><th>Side</th><th>Qty</th><th>Status</th></tr></thead>
            <tbody>
              {(status?.open_orders || []).map((o) => (
                <tr key={o.order_id}>
                  <td><span className={`badge ${o.side === 'BUY' ? 'buy' : 'sell'}`}>{o.side}</span></td>
                  <td className="mono">{o.qty}</td>
                  <td className="mono">{o.status}</td>
                </tr>
              ))}
              {(status?.open_orders || []).length === 0 &&
                <tr><td colSpan={3} className="muted">Koi open order nahi</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
