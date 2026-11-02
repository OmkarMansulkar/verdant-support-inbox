import { useCallback, useEffect, useRef } from 'react'
import { agentApi } from '../api.ts'
import { formatTime } from '../format.ts'
import { usePolling } from '../usePolling.ts'
import DraftPanel from './DraftPanel.tsx'

const POLL_MS = 4000

/** One conversation: every message in order, then the draft waiting for review. */
export default function ConversationPage({ conversationId }: { conversationId: string }) {
  const load = useCallback(() => agentApi.conversation(conversationId), [conversationId])
  const { data, error, reload } = usePolling(load, POLL_MS)
  const listRef = useRef<HTMLOListElement>(null)

  // Keep the newest message in view when one arrives.
  const messageCount = data?.messages.length ?? 0
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messageCount])

  if (!data) {
    return <section className="card conversation">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</section>
  }

  const { conversation, messages, draft } = data
  return (
    <section className="card conversation">
      <header className="conversation-header">
        <h2>{conversation.customer_name}</h2>
        <span className="muted">{conversation.customer_phone}</span>
      </header>
      {error && <p className="error">Couldn't refresh: {error}</p>}

      <ol className="messages" ref={listRef}>
        {messages.map((m) => (
          <li key={m.id} className={`message message-${m.sender}`}>
            {/* Plain text only: React escapes it, so customer text can never become HTML. */}
            <p>{m.body}</p>
            <span className="meta">
              {m.sender === 'agent' ? (m.agent_name ?? 'Agent') : conversation.customer_name} · {formatTime(m.created_at)}
            </span>
          </li>
        ))}
      </ol>

      <DraftPanel draft={draft} onChanged={reload} />
    </section>
  )
}
