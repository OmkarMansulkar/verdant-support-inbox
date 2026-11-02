import { useEffect, useState } from 'react'
import { agentApi, ApiError, type Draft } from '../api.ts'

type Props = { draft: Draft | null; onChanged: () => void }

/**
 * The editable draft box with Approve and Retry.
 *
 * The page polls every few seconds, so the draft can change under the agent:
 * the AI finishes writing, or a new customer message replaces the draft. The
 * box is refilled automatically only while the agent hasn't edited it; once
 * they have, their text is kept and a notice offers to load the new draft.
 */
export default function DraftPanel({ draft, onChanged }: Props) {
  const [text, setText] = useState('')
  const [loaded, setLoaded] = useState<{ id: string; body: string } | null>(null) // what's in the box
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const edited = loaded !== null && text !== loaded.body
  const latestBody = draft?.body ?? ''
  const isNewer = draft !== null && loaded !== null && (draft.id !== loaded.id || latestBody !== loaded.body)

  function loadDraft() {
    if (!draft) return
    setText(latestBody)
    setLoaded({ id: draft.id, body: latestBody })
  }

  // Runs when the draft from the server changes (not on every keystroke).
  useEffect(() => {
    if (draft && (loaded === null || (isNewer && !edited))) loadDraft()
  }, [draft?.id, latestBody])

  async function run(action: () => Promise<unknown>, success: string | null) {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      setMessage(success)
      if (success) {
        setLoaded(null) // the next draft that arrives fills the box
        setText('')
      }
    } catch (e) {
      // 409s explain what happened ("Already approved by Rahul"), so show them as-is.
      setMessage(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
      onChanged()
    }
  }

  if (!draft) {
    return (
      <div className="draft">
        {message && <p className="notice">{message}</p>}
        <p className="muted">No draft waiting. A new one appears when the customer writes again.</p>
      </div>
    )
  }

  const pending = draft.status === 'pending'
  return (
    <div className="draft">
      <div className="draft-heading">
        <h3>Suggested reply</h3>
        {draft.model && <span className="muted">AI draft · {draft.model}</span>}
      </div>

      {pending && <p className="muted">The AI is writing a draft…</p>}
      {pending && draft.retryable && <p className="error">This is taking longer than expected. Try Retry.</p>}
      {draft.status === 'failed' && (
        <p className="error">
          The AI couldn't write a draft{draft.error ? `: ${draft.error}` : ''}. Retry, or type the reply yourself.
        </p>
      )}
      {draft.needs_human && <p className="flag">Needs attention: {draft.flag_reason}</p>}
      {isNewer && edited && (
        <p className="notice">
          {draft.id !== loaded?.id ? 'The customer sent another message and there is a new draft.' : 'The AI draft is ready.'}{' '}
          Your edits are kept. <button onClick={loadDraft}>Use the new draft</button>
        </p>
      )}

      <textarea
        aria-label="Reply to send"
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={pending || busy}
        rows={5}
        maxLength={4000}
        placeholder={pending ? '' : 'Type the reply…'}
      />
      {message && <p className="notice">{message}</p>}

      <div className="actions">
        <button
          className="primary"
          disabled={pending || busy || text.trim() === ''}
          onClick={() => run(() => agentApi.approve(draft.id, text), 'Reply approved and saved.')}
        >
          Approve
        </button>
        {draft.retryable && (
          <button disabled={busy} onClick={() => run(() => agentApi.retry(draft.id), null)}>
            Retry AI draft
          </button>
        )}
      </div>
    </div>
  )
}
