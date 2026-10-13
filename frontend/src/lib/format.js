// Small helpers shared by every page.

export const deskUrl = (doctype, name) => {
  const slug = doctype.toLowerCase().replace(/ /g, '-')
  return name ? `/app/${slug}/${encodeURIComponent(name)}` : `/app/${slug}`
}

// Frappe returns "YYYY-MM-DD HH:mm:ss(.ffffff)" in the system timezone.
const parse = (value) => (value ? new Date(String(value).replace(' ', 'T')) : null)

export function timeAgo(value) {
  const d = parse(value)
  if (!d || isNaN(d)) return '—'
  const s = Math.round((Date.now() - d.getTime()) / 1000)
  if (s < 45) return 'just now'
  const units = [
    [60, 'minute'], [3600, 'hour'], [86400, 'day'], [604800, 'week'], [2629800, 'month'], [31557600, 'year'],
  ]
  for (let i = units.length - 1; i >= 0; i--) {
    const [secs, label] = units[i]
    if (Math.abs(s) >= secs) {
      const n = Math.round(s / secs)
      return n < 0 ? `in ${-n} ${label}${n === -1 ? '' : 's'}` : `${n} ${label}${n === 1 ? '' : 's'} ago`
    }
  }
  return 'just now'
}

export function dateTime(value) {
  const d = parse(value)
  if (!d || isNaN(d)) return '—'
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export const shortDay = (iso) =>
  new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

// Turn a frappe-js-sdk error into one readable line.
export function errorText(err) {
  if (!err) return ''
  try {
    if (err._server_messages) {
      const msgs = JSON.parse(err._server_messages).map((m) => JSON.parse(m).message)
      return stripHtml(msgs.join(' '))
    }
  } catch {
    /* fall through */
  }
  if (err.exception) return stripHtml(String(err.exception).split(':').slice(1).join(':').trim() || err.exception)
  return stripHtml(err.message || 'Something went wrong.')
}

export function stripHtml(s) {
  const div = document.createElement('div')
  div.innerHTML = s
  return div.textContent || ''
}
