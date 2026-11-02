/** "14:05" for today, "2 Nov, 14:05" for earlier days, in the viewer's time zone. */
export function formatTime(iso: string): string {
  const date = new Date(iso)
  const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (date.toDateString() === new Date().toDateString()) return time
  return `${date.toLocaleDateString([], { day: 'numeric', month: 'short' })}, ${time}`
}
