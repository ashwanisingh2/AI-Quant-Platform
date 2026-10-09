import { useEffect, useState } from 'react'
import Overview from './pages/Overview'
import AgentConsole from './pages/AgentConsole'
import Backtests from './pages/Backtests'
import DataPage from './pages/Data'
import { apiGet, wsUrl } from './api'

const TABS = [
  { id: 'overview', label: '📊 Overview' },
  { id: 'agent', label: '🤖 Agent Console' },
  { id: 'backtests', label: '🧠 Backtests' },
  { id: 'data', label: '💾 Data' },
]

export default function App() {
  const [tab, setTab] = useState('overview')
  const [health, setHealth] = useState(null)
  const [events, setEvents] = useState([])

  useEffect(() => {
    apiGet('/health').then(setHealth).catch(() => setHealth({ status: 'down' }))
  }, [])

  // WebSocket — live events (pages inhe 'ws-event' se sunte hain)
  useEffect(() => {
    let ws
    const connect = () => {
      ws = new WebSocket(wsUrl('/ws/events'))
      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data)
        setEvents((prev) => [ev, ...prev].slice(0, 30))
        window.dispatchEvent(new CustomEvent('ws-event', { detail: ev }))
      }
      ws.onclose = () => setTimeout(connect, 2000)
    }
    connect()
    return () => ws && ws.close()
  }, [])

  const Page = { overview: Overview, agent: AgentConsole, backtests: Backtests, data: DataPage }[tab]

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">🤖 AI Quant Platform</div>
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
