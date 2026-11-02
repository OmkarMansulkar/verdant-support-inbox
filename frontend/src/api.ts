// Calls to the backend's agent API, and the shapes it returns.
// Every call sends the agent's Supabase access token; the backend checks it.

import { API_URL } from './config.ts'
import { supabase } from './supabase.ts'

export type DraftStatus = 'pending' | 'ready' | 'failed'

export type InboxItem = {
  id: string
  customer_name: string
  customer_phone: string
  last_message_preview: string
  last_message_at: string
  draft_status: DraftStatus | null // null: nothing waiting for review
  needs_human: boolean
  draft_retryable: boolean
}

export type Message = {
  id: string
  sender: 'customer' | 'agent'
  body: string
  created_at: string
  agent_name: string | null
}

export type Draft = {
  id: string
  status: DraftStatus
  body: string | null // null while pending, or when generation failed
  needs_human: boolean
  flag_reason: string | null
  error: string | null
  model: string | null
  attempts: number
  message_id: string
  updated_at: string
  retryable: boolean
}

export type ConversationDetail = {
  conversation: { id: string; status: string; customer_name: string; customer_phone: string; customer_external_id: string }
  messages: Message[]
  draft: Draft | null
}

export type AgentProfile = { display_name: string; brand_id: string }

/** An error response from the API. `message` is safe to show to the agent. */
export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function agentRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!API_URL || !supabase) throw new ApiError(0, 'The app is not configured (see the banner above).')
  // getSession() returns a refreshed token if the old one has expired.
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (!token) throw new ApiError(401, 'Please sign in again.')

  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the server. It may be waking up; retrying shortly.')
  }

  if (response.status === 401) {
    // Session expired or revoked: signing out sends the agent back to the sign-in form.
    await supabase.auth.signOut()
    throw new ApiError(401, 'Your session has expired. Please sign in again.')
  }
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  return (await response.json()) as T
}

/** FastAPI errors are {detail: string} or {detail: [{msg}, ...]} for validation. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg
  } catch {
    // not JSON, e.g. a proxy error page while the server restarts
  }
  return `Request failed (HTTP ${response.status})`
}

export const agentApi = {
  me: () => agentRequest<AgentProfile>('/api/agent/me'),
  inbox: () => agentRequest<InboxItem[]>('/api/agent/conversations'),
  conversation: (id: string) => agentRequest<ConversationDetail>(`/api/agent/conversations/${id}`),
  approve: (draftId: string, text: string) =>
    agentRequest<Message>(`/api/agent/drafts/${draftId}/approve`, { method: 'POST', body: JSON.stringify({ text }) }),
  retry: (draftId: string) => agentRequest<{ status: string }>(`/api/agent/drafts/${draftId}/retry`, { method: 'POST' }),
}
