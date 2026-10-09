import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api'

export default function FnoPage() {
  const [underlyings, setUnderlyings] = useState([])
  const [underlying, setUnderlying] = useState('NIFTY')
  const [spot, setSpot] = useState('')
  const [chain, setChain] = useState(null)
  const [loading, setLoading] = useState(false)
  const [fetched, setFetched] = useState({})
  const [error, setError] = useState(null)

  useEffect(() => {
    apiGet('/fno/underlyings').then((r) => setUnderlyings(r.underlyings)).catch(() => {})
  }, [])

  const load = async (und = underlying, sp = spot) => {
    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams({ underlying: und })
      if (sp) q.set('spot', sp)
      const r = await apiGet(`/fno/chain?${q}`)
      setChain(r)
    } catch (e) {
      setError(String(e.message || e))
    }
    setLoading(false)
  }
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchContract = async (symbol) => {
    setFetched((f) => ({ ...f, [symbol]: '…' }))
    try {
      await apiPost('/data/fetch', { provider: 'mock', symbol, days: 90 })
      setFetched((f) => ({ ...f, [symbol]: '✅' }))
    } catch (e) {
      setFetched((f) => ({ ...f, [symbol]: '❌' }))
      setError(String(e.message || e))
    }
  }

  const fmt = (v) => `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

  return (
    <div>
      <div className="card">
        <h3>📊 FnO — Option Chain</h3>
        <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: -6 }}>
          ⚠️ Synthetic/mock data — sirf demo ke liye. Real chain baad mein broker se aayegi.
        </p>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <select value={underlying} onChange={(e) => { setUnderlying(e.target.value); load(e.target.value) }}>
            {underlyings.map((u) => (
              <option key={u.symbol} value={u.symbol}>{u.symbol} (lot {u.lot_size})</option>
            ))}
          </select>
          <input
            type="number" placeholder="Spot (optional)" value={spot}
            onChange={(e) => setSpot(e.target.value)} style={{ width: 140 }}
          />
          <button className="btn" onClick={() => load()} disabled={loading}>
            {loading ? 'Loading…' : '🔄 Load Chain'}
          </button>
        </div>
      </div>

      {error && <div className="card" style={{ color: 'var(--red)' }}>❌ {error}</div>}

      {chain && (
        <div className="card">
          <h3>
            {chain.underlying} · Spot {fmt(chain.spot)} · Lot {chain.lot_size} · Expiry {chain.expiry}
          </h3>
          <table>
            <thead>
              <tr>
                <th>Strike</th>
                <th>CE Premium</th>
                <th>CE Symbol</th>
                <th>CE</th>
                <th>PE Premium</th>
                <th>PE Symbol</th>
                <th>PE</th>
              </tr>
            </thead>
            <tbody>
              {chain.chain.map((r) => (
                <tr key={r.strike} style={r.atm ? { background: 'rgba(88,166,255,0.08)' } : undefined}>
                  <td>
                    {r.strike.toLocaleString('en-IN')}
                    {r.atm && <span className="badge pending" style={{ marginLeft: 6 }}>ATM</span>}
                  </td>
                  <td style={{ color: r.ce_itm ? 'var(--green)' : 'var(--text)' }}>{fmt(r.ce.premium)}</td>
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{r.ce.symbol}</td>
                  <td>
                    <button className="btn sm ghost" disabled={!!fetched[r.ce.symbol]}
                      onClick={() => fetchContract(r.ce.symbol)}>
                      {fetched[r.ce.symbol] || 'Fetch'}
                    </button>
                  </td>
                  <td style={{ color: r.pe_itm ? 'var(--red)' : 'var(--text)' }}>{fmt(r.pe.premium)}</td>
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{r.pe.symbol}</td>
                  <td>
                    <button className="btn sm ghost" disabled={!!fetched[r.pe.symbol]}
                      onClick={() => fetchContract(r.pe.symbol)}>
                      {fetched[r.pe.symbol] || 'Fetch'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 10 }}>
            💾 <b>Fetch</b> dabao → contract ka data store ho jayega → 💾 Data tab mein dekho →
            backtest / paper / live kar sakte ho. ⚠️ F&amp;O = leverage — risk limits hamesha lagti hain.
          </p>
        </div>
      )}
    </div>
  )
}
