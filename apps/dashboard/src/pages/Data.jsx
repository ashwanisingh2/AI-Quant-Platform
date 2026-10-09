import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { apiGet, apiPost } from '../api'

export default function DataPage() {
  const [instruments, setInstruments] = useState([])
  const [form, setForm] = useState({ provider: 'mock', symbol: 'RELIANCE', exchange: 'NSE', days: 120 })
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState(null)
  const [candles, setCandles] = useState([])
  const chartBoxRef = useRef(null)
  const seriesRef = useRef(null)

  const load = async () => {
    try { setInstruments((await apiGet('/instruments')).instruments) } catch (e) { /* retry */ }
  }
  useEffect(() => { load() }, [])

  const fetchData = async () => {
    setBusy(true)
    try {
      await apiPost('/data/fetch', { ...form, days: Number(form.days) })
      load()
    } catch (e) { alert(String(e.message || e)) }
    setBusy(false)
  }

  const show = async (instrument) => {
    setSelected(instrument)
    setCandles([])
    const r = await apiGet(`/data/candles?instrument=${encodeURIComponent(instrument)}&limit=250`)
    setCandles(r.candles)
  }

  useEffect(() => {
    if (!candles.length || !chartBoxRef.current) return
    if (!seriesRef.current) {
      const chart = createChart(chartBoxRef.current, {
        width: chartBoxRef.current.clientWidth,
        height: 320,
        layout: { background: { color: 'transparent' }, textColor: '#8b949e' },
        grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
        rightPriceScale: { borderColor: '#30363d' },
        timeScale: { borderColor: '#30363d' },
      })
      seriesRef.current = chart.addCandlestickSeries({
        upColor: '#3fb950', downColor: '#f85149',
        wickUpColor: '#3fb950', wickDownColor: '#f85149', borderVisible: false,
      })
    }
    seriesRef.current.setData(candles.map((c) => ({
      time: Math.floor(new Date(c.timestamp).getTime() / 1000),
      open: c.open, high: c.high, low: c.low, close: c.close,
    })))
  }, [candles])

  return (
    <div>
      <div className="card">
        <h3>💾 Fetch Data</h3>
        <div className="form-row">
          <div>
            <label>Provider</label>
            <select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
              <option value="mock">mock (no internet)</option>
              <option value="bhavcopy">bhavcopy (REAL NSE, no key)</option>
              <option value="kite">kite (Zerodha, env keys)</option>
            </select>
          </div>
          <div><label>Symbol</label><input value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })} /></div>
          <div><label>Exchange</label><input value={form.exchange} onChange={(e) => setForm({ ...form, exchange: e.target.value.toUpperCase() })} /></div>
          <div><label>Days</label><input type="number" value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value })} /></div>
          <div><button className="btn" disabled={busy} onClick={fetchData}>{busy ? '⏳ Fetching...' : '⬇ Fetch'}</button></div>
        </div>
        {form.provider === 'bhavcopy' &&
          <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>NSE se download mein 30-60 sec lag sakte hain.</p>}
      </div>

      <div className="card">
        <h3>📦 Stored Instruments ({instruments.length})</h3>
        <table>
          <thead><tr><th>Instrument</th><th>Candles</th><th>From</th><th>To</th><th>Last Close</th><th></th></tr></thead>
          <tbody>
            {instruments.map((i) => (
              <tr key={i.instrument}>
                <td className="mono">{i.instrument}</td>
                <td className="mono">{i.candles}</td>
                <td className="mono muted">{i.from}</td>
                <td className="mono muted">{i.to}</td>
                <td className="mono">₹{i.last_close}</td>
                <td><button className="btn ghost sm" onClick={() => show(i.instrument)}>📈 Chart</button></td>
              </tr>
            ))}
            {instruments.length === 0 &&
              <tr><td colSpan={6} className="muted">Koi data nahi — upar fetch karo.</td></tr>}
          </tbody>
        </table>
      </div>

      {selected && (
        <div className="card">
          <h3>📈 {selected}</h3>
          {candles.length > 0
            ? <div className="chart-box" ref={chartBoxRef} style={{ minHeight: 320 }} />
            : <p className="muted">Loading...</p>}
        </div>
      )}
    </div>
  )
}
