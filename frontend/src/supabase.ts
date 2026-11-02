// Supabase is used only for agent sign-in. supabase-js keeps the session in
// localStorage and refreshes the access token before it expires.
// null when the settings are missing (the app shows a banner instead).

import { createClient } from '@supabase/supabase-js'
import { SUPABASE_ANON_KEY, SUPABASE_URL } from './config.ts'

export const supabase =
  SUPABASE_URL && SUPABASE_ANON_KEY ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY) : null
