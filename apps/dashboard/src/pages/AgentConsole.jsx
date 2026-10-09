import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api'

const DIR_BADGE = { BUY: 'buy', SELL: 'sell', HOLD: 'hold' }
const DIR_EMOJI = { BUY: '🟢', SELL: '🔴', HOLD: '⚪' }

export default function AgentConsole() {
  const [runs, setRuns] = useState([])
  const [instruments, setInstruments] = useState([])
  const [instrument, setInstrument] = useState('NSE:TESTCO')
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(null)

  const load = async () => {
    try {
      setRuns((await apiGet('/agent/runs')).runs)
      setInstruments((await apiGet('/instruments')).instruments)
    } catch (e) { /* retry */ }
  }

  useEffect(() => {
    load()
    const onWs = (e) => {
      if (['signal', 'signal.approved', 'signal.rejected'].includes(e.detail?.type)) load()
    }
    window.addEventListener('ws-event', onWs)
    return () => window.removeEventListener('ws-event', onWs)
  }, [])

  const analyze = async () => {
    setBusy(true)
    try { await apiPost('/agent/analyze', { instrument, llm: 'mock' }); load() }
    catch (e) { alert(String(e.message || e)) }
    setBusy(false)
  }
  const approve = async (id) => { await apiPost(`/signals/${id}/approve`); load() }
  const reject = async (id) => { await apiPost(`/signals/${id}/reject`); load() }

  return (
    <div>
      <div className="card">
        <h3>🤖 Run AI Analysis</h3>
        <div className="form-row">
          <div>
            <label>Instrument</label>
            <select value={instrument} onChange={(e) => setInstrument(e.target.value)}>
              {instruments.map((i) => <option key={i.instrument} value={i.instrument}>{i.instrument}</option>)}
              {instruments.length === 0 && <option>NSE:TESTCO</option>}
            </select>
          </div>
          <div><button className="btn" disabled={busy} onClick={analyze}>{busy ? '⏳ Analyzing...' : '▶ Analyze'}</button></div>
        </div>
        <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
          Pipeline: Analyst → Trader → Risk. Mock LLM (no API key) — real LLM ke liye LLM_MODEL/LLM_API_KEY env set karo.
        </p>
      </div>

      <div className="card">
        <h3>📜 Signals ({runs.length})</h3>
        {runs.length === 0 && <p className="muted">Abhi koi signal nahi — upar "Analyze" dabao.</p>}
        {runs.map((r) => {
          const sig = r.final_signal
          const risk = r.risk_decision?.decision || '?'
          const status = sig.status
          return (
            <div key={r.id} className="card" style={{ background: 'var(--bg)' }}>
              <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  <span className="mono muted">{r.id}</span>
                  <strong className="mono">{r.instrument}</strong>
                  <span className={`badge ${DIR_BADGE[sig.direction]}`}>{DIR_EMOJI[sig.direction]} {sig.direction}</span>
                  <span className="mono">conf {sig.confidence}</span>
                  {sig.target_price && <span className="mono muted">target ₹{sig.target_price}</span>}
                  {sig.stoploss && <span className="mono muted">SL ₹{sig.stoploss}</span>}
                </div>
                <div className="row">
                  <span className={`badge ${risk}`}>risk: {risk}</span>
                  <span className={`badge ${status === 'approved' ? 'approve' : status === 'rejected' ? 'veto' : 'pending'}`}>{status}</span>
                  <button className="btn ghost sm" onClick={() => setExpanded(expanded === r.id ? null : r.id)}>
                    {expanded === r.id ? '▲' : '▼'} trace
                  </button>
                </div>
              </div>
              <p style={{ fontSize: 13, marginTop: 6 }}>{sig.reasoning}</p>
              {status === 'pending' && (
                <div className="row" style={{ marginTop: 8 }}>
                  <button className="btn green sm" onClick={() => approve(r.id)}>✅ Approve</button>
                  <button className="btn red sm" onClick={() => reject(r.id)}>❌ Reject</button>
                </div>
              )}
              {expanded === r.id && (
                <div style={{ marginTop: 10 }}>
                  {r.steps.map((s, i) => (
                    <div key={i} style={{ marginBottom: 8 }}>
                      <div className="mono muted" style={{ fontSize: 11 }}>
                        [{s.agent}] {s.model} · {s.tokens} tok · ₹{s.cost_inr} · {s.duration_ms}ms
                      </div>
                      <pre className="trace">{s.output}</pre>
                    </div>
                  ))}
                  <div className="mono muted" style={{ fontSize: 11 }}>
                    Risk: {r.risk_explanation} · Total: {r.total_tokens} tok · ₹{r.total_cost_inr} · {r.duration_ms}ms
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
