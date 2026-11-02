import { useCallback, useEffect, useRef, useState } from 'react'
import { customerApi, type CustomerIdentity } from '../api.ts'
import { formatTime } from '../format.ts'
import { usePolling } from '../usePolling.ts'

const POLL_MS = 4000

// The brief's sample messages, one click to put in the message box.
const SAMPLES = [
  "Hi, my order #4471 hasn't arrived yet. Can I change the delivery address?",
  'What is your return policy?',
  'Do you deliver to Dubai?',
  'Is cash on delivery available for a ₹3,500 order?',
  "I think I'm allergic to the serum I bought. What should I do?",
]

type Props = { who: CustomerIdentity; customerName: string }

/** One customer's conversation as they see it: their messages and approved replies, never drafts. */
export default function CustomerChat({ who: initialWho, customerName }: Props) {
  // The parent remounts this component (key) for a different customer, so the
  // identity is fixed for its lifetime. Freezing it keeps `load` stable: a new
  // object on every parent render would otherwise restart polling each time.
  const [who] = useState(initialWho)
  const load = useCallback(() => customerApi.conversation(who), [who])
  const { data, error, reload } = usePolling(load, POLL_MS)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  // One id per message, reused if the same message is sent again after a failure:
  // if the first attempt did reach the server, the retry is stored as a duplicate, not twice.
  const pendingId = useRef<string | null>(null)
  const listRef = useRef<HTMLOListElement>(null)

  const messages = data?.messages ?? []
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages.length])

  function changeText(value: string) {
    setText(value)
    pendingId.current = null // a different message gets a new id
  }

  async function send(event: { preventDefault(): void }) {
    event.preventDefault()
    const body = text.trim()
    if (!body || sending) return
    pendingId.current ??= crypto.randomUUID()
    setSending(true)
    setSendError(null)
    try {
      await customerApi.send(who, body, pendingId.current) // 'duplicate' also means it's saved
      pendingId.current = null
      setText('')
      reload()
    } catch (e) {
      setSendError(e instanceof Error ? e.message : String(e))
    } finally {
      setSending(false)
    }
  }

  const waitingForReply = messages.length > 0 && messages[messages.length - 1].sender === 'customer'

  return (
    <section className="card conversation customer-chat">
      <header className="conversation-header">
        <h2>Chat with Verdant &amp; Co</h2>
        <span className="muted">as {customerName}</span>
      </header>
      {error && <p className="error">Couldn't refresh: {error}</p>}

      {!data && !error && <p className="muted">Loading…</p>}
      {data && messages.length === 0 && <p className="muted">No messages yet. Say hello, or try a sample below.</p>}
      <ol className="messages" ref={listRef}>
        {messages.map((m) => (
          <li key={m.id} className={`message message-${m.sender}`}>
            {/* Plain text only: React escapes it, so message text can never become HTML. */}
            <p>{m.body}</p>
            <span className="meta">
              {m.sender === 'agent' ? 'Verdant & Co' : 'You'} · {formatTime(m.created_at)}
            </span>
          </li>
        ))}
      </ol>
      {waitingForReply && <p className="muted">Sent. The team will reply here.</p>}

      <div className="samples">
        {SAMPLES.map((sample) => (
          <button key={sample} type="button" onClick={() => changeText(sample)}>
            {sample}
          </button>
        ))}
      </div>
      <form className="compose" onSubmit={send}>
        <textarea
          value={text}
          onChange={(e) => changeText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) send(e) // Enter sends, Shift+Enter is a new line
          }}
          placeholder="Type a message"
          rows={2}
          maxLength={4000}
        />
        <button className="primary" type="submit" disabled={sending || !text.trim()}>
          {sending ? 'Sending…' : 'Send'}
        </button>
      </form>
      {sendError && <p className="error">Not sent: {sendError}</p>}
    </section>
  )
}
