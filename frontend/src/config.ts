// Frontend settings come from Vite env variables, baked in at build time.
// A missing value shows an error banner instead of silently calling the wrong URL.

export const API_URL: string | undefined = import.meta.env.VITE_API_URL?.replace(/\/+$/, '')
