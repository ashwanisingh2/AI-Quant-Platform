import { useEffect, useState } from 'react'
import Overview from './pages/Overview'
import AgentConsole from './pages/AgentConsole'
import Backtests from './pages/Backtests'
import DataPage from './pages/Data'
import FnoPage from './pages/Fno'
import Live from './pages/Live'
import Operations from './pages/Operations'
import Radar from './pages/Radar'
import { apiGet, wsUrl, setAuthToken, getAuthToken } from './api'

const TABS = [
  { id: 'radar', icon: '◉', label: 'Market radar', description: 'Daily strength, sector breadth and transparent signal evidence' },
  { id: 'operations', icon: '◈', label: 'Command center', description: 'System health, session history and recovery' },
  { id: 'agent', icon: '◎', label: 'Research desk', description: 'Evidence, model reasoning and human approval' },
  { id: 'backtests', icon: '↗', label: 'Strategy lab', description: 'Reproducible experiments on historical data' },
  { id: 'overview', icon: '▤', label: 'Paper portfolio', description: 'Simulated capital. Observable decisions.' },
  { id: 'live', icon: '⇄', label: 'Execution', description: 'Broker connections and controlled execution' },
  { id: 'data', icon: '▥', label: 'Market data', description: 'Inspect and manage the local market dataset' },
  { id: 'fno', icon: '◇', label: 'Derivatives sandbox', description: 'Synthetic option chains for research only' },
]

export default function App() {
  const [authenticated, setAuthenticated] = useState(false)
  const [credential, setCredential] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState('operations')
  const [health, setHealth] = useState(null)
  const [events, setEvents] = useState([])
  const [stream, setStream] = useState(false)
  const lock = () => { setAuthToken(''); setCredential(''); setEvents([]); setAuthenticated(false) }
  const unlock = async (event) => {
    event.preventDefault(); setBusy(true); setError('')
    setAuthToken(credential)
    try { await apiGet('/brokers'); setCredential(''); setAuthenticated(true) }
    catch { setAuthToken(''); setError('Access denied. Check your operator token and server configuration.') }
    finally { setBusy(false) }
  }
  useEffect(() => {
    const load = () => apiGet('/health').then(setHealth).catch(() => setHealth({ status: 'down' }))
    load(); const interval = setInterval(load, 15000)
    return () => clearInterval(interval)
  }, [])
  useEffect(() => {
    const handler = () => { lock(); setError('Session access ended. Unlock again to continue.') }
    window.addEventListener('auth-expired', handler)
    return () => window.removeEventListener('auth-expired', handler)
  }, [])
  useEffect(() => {
    if (!authenticated) return
    let ws, retry, disposed = false
    const connect = () => {
      ws = new WebSocket(wsUrl('/ws/events'))
      ws.onopen = () => { if (!disposed) ws.send(JSON.stringify({ token: getAuthToken() })) }
      ws.onmessage = (e) => {
        if (disposed) return
        setStream(true)
        try {
          const ev = JSON.parse(e.data)
          setEvents(prev => [ev, ...prev].slice(0, 30))
          window.dispatchEvent(new CustomEvent('ws-event', { detail: ev }))
        } catch { /* Ignore invalid frames; REST remains available. */ }
      }
      ws.onclose = (event) => {
        setStream(false)
        if (disposed) return
        if (event.code === 1008) { lock(); return }
        retry = setTimeout(connect, 3000)
      }
    }
    connect()
    return () => { disposed = true; clearTimeout(retry); if (ws) ws.close(); setStream(false) }
  }, [authenticated])

  if (!authenticated) return (
    <div className="login-shell">
      <section className="login-story">
        <div className="wordmark"><span className="brand-mark">Q</span> QUANT / PLATFORM <small>V2</small></div>
        <div><span className="eyebrow">THE INDIA RESEARCH & EXECUTION WORKSPACE</span>
          <h1>Clarity before<br /><em>every decision.</em></h1>
          <p>One workspace for research, strategy testing, paper portfolios and controlled broker execution.</p>
          <div className="login-principles"><span>01 / Shared strategy logic</span><span>02 / Durable order records</span><span>03 / Human oversight</span></div>
        </div>
        <div className="login-foot">Built for deliberate trading. Live execution is disabled by default.</div>
      </section>
      <section className="login-panel"><form onSubmit={unlock}>
        <span className="eyebrow">OPERATOR ACCESS</span><h2>Welcome to your desk.</h2>
        <p className="muted">Use your private operator token to unlock the workspace.</p>
        <label htmlFor="operator-token">Operator token</label>
        <input id="operator-token" type="password" autoComplete="off" value={credential} onChange={e => setCredential(e.target.value)} required />
        <button className="btn login-submit" disabled={busy}>{busy ? 'Verifying access…' : 'Unlock workspace →'}</button>
        {error && <p className="notice danger" role="alert">{error}</p>}
        <p className="login-note">Your token stays in browser memory and is cleared when you lock or reload.</p>
        <div className={`connection ${health?.status === 'ok' ? 'connected' : ''}`}><i /> {health?.status === 'ok' ? 'API available' : 'Waiting for API'}</div>
      </form></section>
    </div>
  )

  const current = TABS.find(t => t.id === tab)
  const Page = { radar: Radar, operations: Operations, overview: Overview, live: Live, fno: FnoPage, agent: AgentConsole, backtests: Backtests, data: DataPage }[tab]
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="wordmark"><span className="brand-mark">Q</span><div>QUANT<span className="brand-sub">PLATFORM / V2</span></div></div>
        <div className="workspace-label">WORKSPACE <span>INDIA</span></div>
        <nav aria-label="Workspace navigation">{TABS.map(t => <button key={t.id} aria-label={t.label} className={`nav-item ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)} aria-current={tab === t.id ? 'page' : undefined}><span>{t.icon}</span>{t.label}</button>)}</nav>
        <div className="sidebar-bottom"><div className="operator-avatar">OP</div><div>Operator workspace<small>Private access</small></div><button onClick={lock} className="lock-button" title="Lock workspace" aria-label="Lock workspace">↪</button></div>
      </aside>
      <div className="workspace">
        <header className="workspace-bar"><span>Workspace <span className="crumb">/ {current.label}</span></span><div className="row"><span className={`connection ${health?.status === 'ok' ? 'connected' : ''}`}><i />API {health?.status === 'ok' ? 'online' : 'offline'}</span><span className="stream-label">{stream ? 'Events connected' : 'Events waiting'}</span><span className="environment-tag">{health?.live_trading_enabled ? 'LIVE ENABLED' : 'RESEARCH MODE'}</span></div></header>
        <main className="content"><div className="page-heading"><div><span className="eyebrow">QUANT PLATFORM / {String(TABS.findIndex(t => t.id === tab) + 1).padStart(2, '0')}</span><h1>{current.label}</h1><p>{current.description}</p></div><span className="market-tag">NSE / BSE · IST</span></div><Page events={events} navigate={setTab} /></main>
        <footer className="workspace-footer"><span>Quant Platform V2 · Single operator</span><span>Research results are not verified live performance.</span></footer>
      </div>
    </div>
  )
}
