import { useEffect, useState } from 'react'
import Overview from './pages/Overview'
import AgentConsole from './pages/AgentConsole'
import Backtests from './pages/Backtests'
import DataPage from './pages/Data'
import FnoPage from './pages/Fno'
import Live from './pages/Live'
import { apiGet, wsUrl, setAuthToken, getAuthToken } from './api'

const TABS = [
  { id: 'overview', label: '📊 Overview' },
  { id: 'live', label: '🟢 Live' },
  { id: 'fno', label: '📈 FnO' },
  { id: 'agent', label: '🤖 Agent Console' },
  { id: 'backtests', label: '🧠 Backtests' },
  { id: 'data', label: '💾 Data' },
]

export default function App() {
  const [authenticated, setAuthenticated] = useState(false)
  const [credential, setCredential] = useState('')
  const [error, setError] = useState('')
  const unlock = async (event) => {
    event.preventDefault()
    setAuthToken(credential)
    try {
      await apiGet('/brokers')
      setCredential(''); setError(''); setAuthenticated(true)
    } catch { setAuthToken(''); setError('Access denied. Check the API token and server configuration.') }
  }
  const [tab, setTab] = useState('overview')
  const [health, setHealth] = useState(null)
  const [events, setEvents] = useState([])

  useEffect(() => {
    apiGet('/health').then(setHealth).catch(() => setHealth({ status: 'down' }))
  }, [])

  // WebSocket — live events (pages inhe 'ws-event' se sunte hain)
  useEffect(() => {
    if (!authenticated) return
    let ws, retry
    let disposed = false
    const connect = () => {
      ws = new WebSocket(wsUrl('/ws/events'))
      ws.onopen = () => ws.send(JSON.stringify({ token: getAuthToken() }))
      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data)
        setEvents((prev) => [ev, ...prev].slice(0, 30))
        window.dispatchEvent(new CustomEvent('ws-event', { detail: ev }))
      }
      ws.onclose = (event) => {
        if (event.code === 1008) { setAuthToken(''); setAuthenticated(false); return }
        if (!disposed) retry = setTimeout(connect, 2000)
      }
    }
    connect()
    return () => { disposed = true; clearTimeout(retry); if (ws) ws.close() }
  }, [authenticated])

  if (!authenticated) return (
    <main className="content"><form className="card" onSubmit={unlock}>
      <h2>Unlock AI Quant Platform</h2>
      <p>Enter the operator API token configured on your server.</p>
      <input type="password" aria-label="API token" autoComplete="off" value={credential}
        onChange={(e) => setCredential(e.target.value)} required />
      <button className="btn" type="submit">Unlock</button>
      {error && <p role="alert">{error}</p>}
    </form></main>
  )

  const Page = { overview: Overview, live: Live, fno: FnoPage, agent: AgentConsole, backtests: Backtests, data: DataPage }[tab]

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">🤖 AI Quant Platform</div>
        <button className="btn" onClick={() => { setAuthToken(''); setEvents([]); setAuthenticated(false) }}>Lock</button>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? 'tab active' : 'tab'}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className={`status ${health?.status === 'ok' ? 'ok' : 'down'}`}>
          API {health?.status === 'ok' ? '●' : '○'}
        </div>
      </header>
      <main className="content">
        <Page events={events} />
      </main>
    </div>
  )
}
