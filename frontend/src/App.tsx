import { useEffect, useState } from 'react'
import { API_URL } from './config.ts'

type View = 'customer' | 'agent'
type BackendStatus = 'checking' | 'ok' | 'down'

export default function App() {
  const [view, setView] = useState<View>('customer')
  const [backend, setBackend] = useState<BackendStatus>('checking')

  // Shows whether the API is reachable. On Render's free tier the first
  // request after idle can take up to a minute while the server wakes up.
  useEffect(() => {
    if (!API_URL) return
    fetch(`${API_URL}/health`)
      .then((response) => setBackend(response.ok ? 'ok' : 'down'))
      .catch(() => setBackend('down'))
  }, [])

  return (
    <>
      <header className="topbar">
        <strong>Verdant &amp; Co Support</strong>
        <div className="toggle" role="tablist" aria-label="Choose view">
          <button
            role="tab"
            aria-selected={view === 'customer'}
            className={view === 'customer' ? 'active' : ''}
            onClick={() => setView('customer')}
          >
            Customer
          </button>
          <button
            role="tab"
            aria-selected={view === 'agent'}
            className={view === 'agent' ? 'active' : ''}
            onClick={() => setView('agent')}
          >
            Agent
          </button>
        </div>
        <span className={`status status-${backend}`}>API: {backend}</span>
      </header>

      {!API_URL && <p className="banner-error">VITE_API_URL is not set. See frontend/.env.example.</p>}

      <main>
        {view === 'customer' ? <p>Customer view (Phase 6)</p> : <p>Agent view (Phase 5)</p>}
      </main>
    </>
  )
}
