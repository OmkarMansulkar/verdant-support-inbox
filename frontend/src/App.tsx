import { useEffect, useState } from 'react'
import AgentView from './agent/AgentView.tsx'
import CustomerView from './customer/CustomerView.tsx'
import { API_URL, missingSettings } from './config.ts'

type View = 'customer' | 'agent'
type BackendStatus = 'checking' | 'ok' | 'down'

// The chosen view is kept in the URL (#agent / #customer) so a page refresh stays on it.
const viewFromUrl = (): View => (window.location.hash === '#agent' ? 'agent' : 'customer')

export default function App() {
  const [view, setView] = useState<View>(viewFromUrl)
  const [backend, setBackend] = useState<BackendStatus>('checking')

  function switchView(next: View) {
    setView(next)
    window.history.replaceState(null, '', `#${next}`)
  }

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
            onClick={() => switchView('customer')}
          >
            Customer
          </button>
          <button
            role="tab"
            aria-selected={view === 'agent'}
            className={view === 'agent' ? 'active' : ''}
            onClick={() => switchView('agent')}
          >
            Agent
          </button>
        </div>
        <span className={`status status-${backend}`}>API: {backend}</span>
      </header>

      {missingSettings.length > 0 && (
        <p className="banner-error">Missing settings: {missingSettings.join(', ')}. See frontend/.env.example.</p>
      )}

      <main>{view === 'customer' ? <CustomerView /> : <AgentView />}</main>
    </>
  )
}
