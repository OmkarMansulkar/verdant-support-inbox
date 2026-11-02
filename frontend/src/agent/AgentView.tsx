import type { Session } from '@supabase/supabase-js'
import { useEffect, useState } from 'react'
import { supabase } from '../supabase.ts'
import AgentWorkspace from './AgentWorkspace.tsx'
import SignIn from './SignIn.tsx'

/** Agent view: the sign-in form when signed out, the inbox when signed in. */
export default function AgentView() {
  const [session, setSession] = useState<Session | null | undefined>(undefined) // undefined = still checking

  useEffect(() => {
    if (!supabase) return
    // Fires once with the stored session, then on every sign-in, sign-out and token refresh.
    const { data } = supabase.auth.onAuthStateChange((_event, newSession) => setSession(newSession))
    return () => data.subscription.unsubscribe()
  }, [])

  if (!supabase) return null // the settings banner explains what's missing
  if (session === undefined) return <p className="muted">Loading…</p>
  if (session === null) return <SignIn />
  // Keyed by user, so a token refresh doesn't reset the screen but a different agent starts fresh.
  return <AgentWorkspace key={session.user.id} />
}
