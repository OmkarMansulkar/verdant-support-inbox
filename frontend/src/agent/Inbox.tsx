import { agentApi, type InboxItem } from '../api.ts'
import { formatTime } from '../format.ts'
import { usePolling } from '../usePolling.ts'

const POLL_MS = 4000

type Props = { selectedId: string | null; onSelect: (id: string) => void }

/** Open conversations, newest activity first (the API sorts them). */
export default function Inbox({ selectedId, onSelect }: Props) {
  const { data: items, error } = usePolling(agentApi.inbox, POLL_MS)

  return (
    <nav className="card inbox" aria-label="Conversations">
      <h2>Inbox</h2>
      {error && <p className="error">{error}</p>}
      {items === null && !error && <p className="muted">Loading…</p>}
      {items?.length === 0 && <p className="muted">No conversations yet.</p>}
      <ul>
        {items?.map((item) => (
          <li key={item.id}>
            <button className={item.id === selectedId ? 'inbox-item selected' : 'inbox-item'} onClick={() => onSelect(item.id)}>
              <span className="inbox-top">
                <strong>{item.customer_name}</strong>
                <time dateTime={item.last_message_at}>{formatTime(item.last_message_at)}</time>
              </span>
              <span className="preview">{item.last_message_preview}</span>
              <DraftBadges item={item} />
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function DraftBadges({ item }: { item: InboxItem }) {
  return (
    <span className="badges">
      {item.draft_status === 'pending' && <span className="badge">Drafting…</span>}
      {item.draft_status === 'ready' && <span className="badge badge-ready">Draft ready</span>}
      {item.draft_status === 'failed' && <span className="badge badge-failed">Draft failed</span>}
      {item.draft_status === null && <span className="badge">Replied</span>}
      {item.needs_human && <span className="badge badge-flag">Needs attention</span>}
    </span>
  )
}
