import { useEffect, useState } from 'react'
import { customerApi, type CustomerIdentity, type TestCustomer } from '../api.ts'
import CustomerChat from './CustomerChat.tsx'

const RETRY_MS = 5000
const SOMEONE_ELSE = '__someone_else__'

/**
 * Customer view (a test tool, no sign-in): pick who you are, then chat.
 * Messages sent here go through the same server code as the webhook.
 */
export default function CustomerView() {
  const [testCustomers, setTestCustomers] = useState<TestCustomer[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [choice, setChoice] = useState('') // a test customer id, or SOMEONE_ELSE
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [typed, setTyped] = useState<{ name: string; phone: string } | null>(null)

  // Load the picker; keep retrying while the server wakes up (Render free tier).
  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    async function load() {
      try {
        const customers = await customerApi.testCustomers()
        if (cancelled) return
        setTestCustomers(customers)
        setChoice((current) => current || customers[0]?.id || SOMEONE_ELSE)
        setLoadError(null)
      } catch (e) {
        if (cancelled) return
        setLoadError(e instanceof Error ? e.message : String(e))
        timer = window.setTimeout(load, RETRY_MS)
      }
    }
    load()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [])

  if (!testCustomers) {
    return <p className="muted">{loadError ? `${loadError} Retrying…` : 'Loading…'}</p>
  }

  let who: CustomerIdentity | null = null
  let whoKey = ''
  let whoName = ''
  if (choice === SOMEONE_ELSE) {
    if (typed) {
      who = typed
      whoKey = `typed:${typed.phone}`
      whoName = typed.name
    }
  } else {
    who = { testCustomerId: choice }
    whoKey = `test:${choice}`
    whoName = testCustomers.find((c) => c.id === choice)?.name ?? ''
  }

  return (
    <div className="customer-view">
      <section className="card who">
        <label>
          Chat as
          <select value={choice} onChange={(e) => setChoice(e.target.value)}>
            {testCustomers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.phone})
              </option>
            ))}
            <option value={SOMEONE_ELSE}>Someone else…</option>
          </select>
        </label>

        {choice === SOMEONE_ELSE && (
          <form
            className="typed-customer"
            onSubmit={(e) => {
              e.preventDefault()
              setTyped({ name: name.trim(), phone: phone.trim() })
            }}
          >
            <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
            <input placeholder="Phone, e.g. +91 98000 00004" value={phone} onChange={(e) => setPhone(e.target.value)} required maxLength={32} />
            <button type="submit">Start chatting</button>
          </form>
        )}
        <p className="muted">
          Test tool: messages sent here are handled exactly like webhook deliveries. Drafts are only visible to agents.
        </p>
      </section>

      {/* Keyed by customer, so switching never shows the previous customer's messages. */}
      {who && <CustomerChat key={whoKey} who={who} customerName={whoName} />}
    </div>
  )
}
