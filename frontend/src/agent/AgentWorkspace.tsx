import { useEffect, useState } from 'react'
import { agentApi, ApiError, type AgentProfile } from '../api.ts'
import { supabase } from '../supabase.ts'
import ConversationPage from './ConversationPage.tsx'
import Inbox from './Inbox.tsx'

/** Signed in: confirm the account is an agent, then show the inbox and the open conversation. */
export default function AgentWorkspace() {
  const [agent, setAgent] = useState<AgentProfile | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    agentApi
      .me()
      .then(setAgent)
      .catch((e: ApiError) => setError(e))
  }, [attempt])

  const signOut = () => supabase?.auth.signOut()

  if (error) {
    // 403: a valid Supabase user who isn't in the agents table.
    const text = error.status === 403 ? 'This account is not set up as a support agent.' : error.message
    return (
      <div className="card">
        <p className="error">{text}</p>
        {error.status !== 403 && (
          <button onClick={() => { setError(null); setAttempt((n) => n + 1) }}>Try again</button>
        )}{' '}
        <button onClick={signOut}>Sign out</button>
      </div>
    )
  }
  if (!agent) return <p className="muted">Checking your account… (the server can take up to a minute to wake up)</p>

  return (
    <div className="workspace">
      <div className="workspace-bar">
        <span>
          Signed in as <strong>{agent.display_name}</strong>
        </span>
        <button onClick={signOut}>Sign out</button>
      </div>
      <div className="panes">
        <Inbox selectedId={selectedId} onSelect={setSelectedId} />
        {selectedId ? (
          // Keyed by id: switching conversations starts with a fresh page and an empty draft box.
          <ConversationPage key={selectedId} conversationId={selectedId} />
        ) : (
          <section className="card empty">Select a conversation.</section>
        )}
      </div>
    </div>
  )
}
