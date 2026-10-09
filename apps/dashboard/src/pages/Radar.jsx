import { useEffect, useState } from 'react'
import { apiGet } from '../api'

export default function Radar() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [direction, setDirection] = useState('all')
  const [selected, setSelected] = useState(null)
  useEffect(() => {
    let disposed = false
    const load = async () => {
      setBusy(true)
      try { const result = await apiGet('/radar'); if (!disposed) { setData(result); setError('') } }
      catch { if (!disposed) setError('Refresh failed. Any displayed snapshot may be outdated.') }
      finally { if (!disposed) setBusy(false) }
    }
    load()
    const timer = setInterval(load, 60000)
    return () => { disposed = true; clearInterval(timer) }
  }, [])
  const rows = (data?.rows || []).filter(r => r.instrument.toLowerCase().includes(query.toLowerCase()) && (direction === 'all' || r.direction === direction))
  const active = data?.rows.find(r => r.instrument === selected) || rows[0]
  const chart = active?.candles || []
  const low = Math.min(...chart.map(c => c.close), active?.support ?? Infinity)
  const high = Math.max(...chart.map(c => c.close), active?.resistance ?? -Infinity)
  const y = value => 170 - (value - low) / (high - low || 1) * 150
  return <div className="radar">
    <div className="notice">{data?.notice || 'Loading stored daily snapshot…'} <strong>No automatic orders.</strong></div>
    {error && <p className="notice danger" role="alert">{error}</p>}
    <div className="radar-stats">
      <div className="card"><small>SNAPSHOT SESSION</small><h2>{data?.session || 'No data'}</h2><span>{busy ? 'Refreshing…' : 'Checks stored data every 60s'}</span></div>
      {['advancing', 'declining', 'unchanged'].map(k => <div className="card" key={k}><small>{k.toUpperCase()}</small><h2>{data?.breadth[k] ?? '—'}</h2><span>Previous close comparison</span></div>)}
    </div>
    <p className="muted">{data?.universe} · Coverage: {data?.coverage ?? 0}. Breadth uses the entire snapshot, independent of filters.</p>
    <div className="radar-layout"><section className="card">
      <h3>Strength board</h3><div className="form-row"><div><label htmlFor="radar-search">Search stock</label><input id="radar-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Symbol or exchange" /></div><div><label htmlFor="radar-direction">Direction</label><select id="radar-direction" value={direction} onChange={e => setDirection(e.target.value)}>{['all', 'bullish', 'bearish', 'neutral'].map(v => <option key={v}>{v}</option>)}</select></div></div>
      <div className="radar-table"><table><thead><tr><th>Rank / Stock</th><th>Change</th><th>Strength</th><th>Direction</th></tr></thead><tbody>{rows.map(r => <tr key={r.instrument}><td><button className="radar-stock" onClick={() => setSelected(r.instrument)}>{r.rank}. {r.instrument}</button></td><td>{r.change_pct.toFixed(2)}%</td><td>{r.score.toFixed(2)}×</td><td>{r.direction}</td></tr>)}</tbody></table></div>
      {!rows.length && <p>No matching daily history. Fetch at least 21 sessions in Market data; mock data remains unverified here.</p>}
    </section><section className="card"><h3>{active?.instrument || 'Signal evidence'}</h3>{active && <><p>{active.reason}</p><svg viewBox="0 0 480 200" role="img" aria-label={`${active.instrument} daily close chart with prior 20-session support and resistance`}>
      {[active.support, active.resistance].map((v, i) => <g key={i}><line x1="10" x2="470" y1={y(v)} y2={y(v)} stroke={i ? '#f59e0b' : '#36bca1'} strokeDasharray="5 4" /></g>)}
      <polyline fill="none" stroke="#6b9fff" strokeWidth="2.5" points={chart.map((c, i) => `${10 + i / Math.max(1, chart.length - 1) * 460},${y(c.close)}`).join(' ')} />
    </svg><p className="muted">{chart[0]?.date} → {chart.at(-1)?.date} · Daily close</p><p>Prior 20-session low: ₹{active.support.toFixed(2)}<br />Prior 20-session high: ₹{active.resistance.toFixed(2)}</p><small>Historical range levels; not verified institutional order blocks. Strength is not a probability or trade recommendation.</small></>}</section></div>
    <section className="card"><h3>Sector strength</h3><p className="muted">Equal-weight mean of stock scores. Small bundled taxonomy; unmatched symbols are Unclassified.</p><div className="radar-sectors">{data?.sectors.map(s => <div key={s.sector}><strong>{s.sector}</strong><h2>{s.score.toFixed(2)}×</h2><small>{s.count} loaded stocks</small></div>)}</div></section>
    {!!data?.excluded.length && <details className="card"><summary>{data.excluded.length} instruments excluded</summary>{data.excluded.map(r => <p key={r.instrument}>{r.instrument}: {r.reason}</p>)}</details>}
    {data?.truncated && <p role="alert">Scan capped at 300 loaded instruments.</p>}
  </div>
}
