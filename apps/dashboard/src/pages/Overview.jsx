import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { apiGet, apiPost } from '../api'

export default function Overview() {
  const [portfolio, setPortfolio] = useState(null)
  const [instruments, setInstruments] = useState([])
  const [strategies, setStrategies] = useState({})
  const [form, setForm] = useState({ instrument: 'NSE:TESTCO', strategy: 'ema_cross', speed: 0.5, capital: 1000000 })
  const [busy, setBusy] = useState(false)
  const chartBoxRef = useRef(null)
  const seriesRef = useRef(null)
  const curveLenRef = useRef(0)

  const load = async () => {
    try {
      setPortfolio(await apiGet('/portfolio'))
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

  // equity chart (lightweight-charts)
  useEffect(() => {
    const curve = portfolio?.equity_curve || []
    if (!curve.length || !chartBoxRef.current) return
    if (!seriesRef.current) {
      const chart = createChart(chartBoxRef.current, {
        width: chartBoxRef.current.clientWidth,
        height: 220,
        layout: { background: { color: 'transparent' }, textColor: '#8b949e' },
        grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
        rightPriceScale: { borderColor: '#30363d' },
        timeScale: { borderColor: '#30363d', timeVisible: false, secondsVisible: false },
      })
      seriesRef.current = chart.addLineSeries({ color: '#3fb950', lineWidth: 2 })
      chartBoxRef.current._chart = chart
    }
    if (curve.length !== curveLenRef.current) {
      const now = Math.floor(Date.now() / 1000)
      seriesRef.current.setData(curve.map((v, i) => ({ time: now - (curve.length - i), value: v })))
      curveLenRef.current = curve.length
    }
  }, [portfolio?.equity_curve?.length])

  const startPaper = async () => {
    setBusy(true)
    try { await apiPost('/paper/start', { ...form, speed: Number(form.speed), capital: Number(form.capital) }) }
    catch (e) { alert(String(e.message || e)) }
    setBusy(false); load()
  }
  const stopPaper = async () => { await apiPost('/paper/stop'); load() }
  const kill = async () => {
    if (!confirm('🚨 KILL SWITCH — saari positions close ho jayengi. Sure?')) return
    try { const result = await apiPost('/kill-switch'); if (result.manual_action_required) alert('Emergency exits are incomplete. Check broker orders and positions immediately.') } catch { alert('Kill request failed. Check your broker account immediately.') }
    load()
  }

  const pnl = portfolio?.total_pnl_pct ?? 0
  const running = portfolio?.running
  const fmt = (v) => (v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })

  return (
    <div>
      <div className="grid">
        <div className="stat"><div className="label">Portfolio Value</div><div className="value mono">₹{fmt(portfolio?.current_equity)}</div></div>
        <div className="stat"><div className="label">Cash</div><div className="value mono">₹{fmt(portfolio?.cash)}</div></div>
        <div className="stat"><div className="label">Total P&L</div><div className={`value mono ${pnl >= 0 ? 'pos' : 'neg'}`}>{pnl >= 0 ? '+' : ''}{pnl}%</div></div>
        <div className="stat"><div className="label">Orders</div><div className="value mono">{portfolio?.n_orders ?? 0}</div></div>
        <div className="stat"><div className="label">Status</div><div className="value">{running ? 'PAPER RUNNING' : portfolio?.killed ? '🚨 KILLED' : '⚪ IDLE'}</div></div>
      </div>

      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3>🚨 Emergency</h3>
          <button className="btn kill" onClick={kill}>KILL SWITCH</button>
        </div>
      </div>

      <div className="card">
        <h3>▶ Paper Trading {running && <span className="badge buy">running</span>}</h3>
        <div className="form-row">
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
          <div><label>Speed (sec/candle)</label><input type="number" step="0.1" value={form.speed} onChange={(e) => setForm({ ...form, speed: e.target.value })} /></div>
          <div><label>Capital (₹)</label><input type="number" value={form.capital} onChange={(e) => setForm({ ...form, capital: e.target.value })} /></div>
          <div>
            {!running
              ? <button className="btn green" disabled={busy} onClick={startPaper}>▶ Start</button>
              : <button className="btn red" onClick={stopPaper}>■ Stop</button>}
          </div>
        </div>
        <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
          Replay mode: stored candles live ki tarah feed hote hain — stored prices (source dependent), simulated money.
          AI signals sirf human approval ke baad execute hote hain.
        </p>
      </div>

      <div className="card">
        <h3>📈 Equity Curve</h3>
        {(portfolio?.equity_curve?.length ?? 0) > 0
          ? <div className="chart-box" ref={chartBoxRef} />
          : <p className="muted">Abhi koi data nahi — paper trading start karo.</p>}
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="card">
          <h3>📦 Open Positions</h3>
          <table>
            <thead><tr><th>Instrument</th><th>Qty</th><th>Avg Price</th></tr></thead>
            <tbody>
              {(portfolio?.positions || []).filter((p) => p.qty > 0).map((p) => (
                <tr key={p.instrument}>
                  <td className="mono">{p.instrument}</td>
                  <td className="mono">{p.qty}</td>
                  <td className="mono">₹{p.avg_price.toFixed(2)}</td>
                </tr>
              ))}
              {(portfolio?.positions || []).filter((p) => p.qty > 0).length === 0 &&
                <tr><td colSpan={3} className="muted">Koi open position nahi</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>🧾 Recent Orders</h3>
          <table>
            <thead><tr><th>Side</th><th>Qty</th><th>Price</th></tr></thead>
            <tbody>
              {(portfolio?.orders || []).slice(-8).reverse().map((o) => (
                <tr key={o.id}>
                  <td><span className={`badge ${o.side === 'BUY' ? 'buy' : 'sell'}`}>{o.side}</span></td>
                  <td className="mono">{o.qty}</td>
                  <td className="mono">₹{o.price}</td>
                </tr>
              ))}
              {(portfolio?.orders || []).length === 0 &&
                <tr><td colSpan={3} className="muted">Abhi koi order nahi</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
