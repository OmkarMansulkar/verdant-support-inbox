// Frontend settings come from Vite env variables, baked in at build time.
// A missing value, or one still containing a <placeholder> from .env.example,
// shows an error banner instead of silently calling the wrong URL.

function read(value: string | undefined): string | undefined {
  if (!value || value.includes('<')) return undefined
  return value.replace(/\/+$/, '')
}

export const API_URL = read(import.meta.env.VITE_API_URL)
export const SUPABASE_URL = read(import.meta.env.VITE_SUPABASE_URL)
export const SUPABASE_ANON_KEY = read(import.meta.env.VITE_SUPABASE_ANON_KEY)

export const missingSettings: string[] = [
  !API_URL && 'VITE_API_URL',
  !SUPABASE_URL && 'VITE_SUPABASE_URL',
  !SUPABASE_ANON_KEY && 'VITE_SUPABASE_ANON_KEY',
].filter((name): name is string => Boolean(name))
