import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api'

export default function Backtests() {
  const [instruments, setInstruments] = useState([])
  const [strategies, setStrategies] = useState({})
  const [results, setResults] = useState([])
  const [form, setForm] = useState({ instrument: 'NSE:TESTCO', strategy: 'ema_cross', start: '', end: '', capital: 1000000, cost_bps: 10, params: {} })
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      setInstruments((await apiGet('/instruments')).instruments)
      setStrategies((await apiGet('/strategies')).strategies)
      setResults((await apiGet('/backtests')).backtests)
    } catch (e) { /* retry */ }
  }
  useEffect(() => { load() }, [])

  const defaults = strategies[form.strategy]?.defaults || {}
  useEffect(() => {
    setForm((f) => ({ ...f, params: { ...defaults } }))
  }, [form.strategy, strategies])

  const run = async () => {
    setBusy(true)
    try {
      await apiPost('/backtests', {
        ...form,
        capital: Number(form.capital),
        cost_bps: Number(form.cost_bps),
        params: Object.fromEntries(Object.entries(form.params).map(([k, v]) => [k, Number(v)])),
      })
      load()
    } catch (e) { alert(String(e.message || e)) }
    setBusy(false)
  }

  return (
    <div>
      <div className="card">
        <h3>🧠 Run Backtest</h3>
        <div className="form-row">
          <div>
            <label>Instrument</label>
            <select value={form.instrument} onChange={(e) => setForm({ ...form, instrument: e.target.value })}>
              {instruments.map((i) => <option key={i.instrument} value={i.instrument}>{i.instrument}</option>)}
              {instruments.length === 0 && <option>NSE:TESTCO</option>}
            </select>
          </div>
          <div>
            <label>Strategy</label>
            <select value={form.strategy} onChange={(e) => setForm({ ...form, strategy: e.target.value })}>
              {Object.keys(strategies).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div><label>From</label><input type="date" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></div>
          <div><label>To</label><input type="date" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} /></div>
          <div><label>Capital ₹</label><input type="number" value={form.capital} onChange={(e) => setForm({ ...form, capital: e.target.value })} /></div>
          <div><label>Estimated costs (bps / turnover)</label><input type="number" min="0" max="1000" value={form.cost_bps} onChange={e => setForm({ ...form, cost_bps: e.target.value })} /></div>
          <div><button className="btn" disabled={busy} onClick={run}>{busy ? '⏳ Running...' : '▶ Run'}</button></div>
        </div>
        <div className="form-row" style={{ marginTop: 10 }}>
          {Object.entries(defaults).map(([k, v]) => (
            <div key={k}>
              <label>{k}</label>
              <input type="number" step="any" value={form.params[k] ?? v}
                onChange={(e) => setForm({ ...form, params: { ...form.params, [k]: e.target.value } })} />
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Saved experiments ({results.length})</h3><p className="muted" style={{ marginBottom: 15 }}>In-sample results. Net return deducts estimated turnover costs; it is not a broker tax or fill simulation.</p>
        <table>
          <thead>
            <tr><th>Instrument</th><th>Strategy</th><th>Period</th><th>Gross return</th><th>Net estimate</th><th>Buy & hold</th><th>Data fingerprint</th><th>Sharpe</th><th>MaxDD</th><th>Trades</th><th>Run at</th></tr>
          </thead>
          <tbody>
            {results.map((r, i) => (
              <tr key={i}>
                <td className="mono">{r.instrument}</td>
                <td>{r.strategy}</td>
                <td className="mono muted">{r.start} → {r.end}</td>
                <td className={`mono ${r.total_return_pct >= 0 ? 'pos' : 'neg'}`}>{r.total_return_pct >= 0 ? '+' : ''}{r.total_return_pct}%</td>
                <td className="mono">{r.net_return_pct ?? "—"}%</td><td className="mono">{r.benchmark_return_pct ?? "—"}%</td><td className="mono" title={r.data_sha256}>{r.data_sha256?.slice(0, 10) || "Legacy run"}</td>
                <td className="mono">{r.sharpe_ratio ?? 'n/a'}</td>
                <td className="mono neg">{r.max_drawdown_pct}%</td>
                <td className="mono">{r.n_trades}</td>
                <td className="mono muted">{String(r.created_at).slice(0, 16)}</td>
              </tr>
            ))}
            {results.length === 0 &&
              <tr><td colSpan={11} className="muted">Abhi koi backtest nahi — upar run karo.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
