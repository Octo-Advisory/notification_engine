// Stand-in for `frappe-react-sdk` in the public demo build (vite --mode demo aliases the package here).
// It serves the sample data in ./data.js from memory, so the dashboard runs without a Frappe site.
// Only the hooks and `call` methods the dashboard uses are implemented.

import { createContext, useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { Info, X } from 'lucide-react'
import { ago, destinations, makeLogs, rules, users } from './data.js'

const REPO = 'https://github.com/Octo-Advisory/notification_engine'

// ---- In-memory store -------------------------------------------------------------------------

const db = {
  'Teams Destination': destinations.map((d) => ({ ...d })),
  'Notification Rule': rules.map((r) => ({ ...r })),
  'Teams User Map': users.map((u) => ({ ...u })),
  'Teams Message Log': makeLogs(),
}
let version = 0
const listeners = new Set()
const changed = () => { version++; listeners.forEach((l) => l()) }
const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l) }
const useVersion = () => useSyncExternalStore(subscribe, () => version)
const later = (ms, fn) => setTimeout(() => { fn(); changed() }, ms)
const respond = (message, ms = 250) => new Promise((r) => setTimeout(() => r({ message }), ms))

const value = (row, field) => row[field] ?? null
function matches(row, [field, op, val]) {
  const v = value(row, field)
  switch (op) {
    case '=': return v === val
    case 'is': return val === 'set' ? v !== null && v !== '' : v === null || v === ''
    case '>=': return v !== null && String(v) >= String(val)
    case 'like': return String(v ?? '').toLowerCase().includes(String(val).replace(/%/g, '').toLowerCase())
    case 'in': return val.includes(v)
    default: return true
  }
}
const where = (doctype, filters = []) => db[doctype].filter((row) => filters.every((f) => matches(row, f)))

function getList(doctype, { filters, orderBy, limit = 20, limit_start = 0, groupBy } = {}) {
  let rows = where(doctype, filters)
  if (groupBy) {
    // Only `count(name) as n` grouped by one field is used (Rules page).
    const counts = {}
    rows.forEach((r) => { counts[r[groupBy]] = (counts[r[groupBy]] || 0) + 1 })
    return Object.entries(counts).map(([k, n]) => ({ [groupBy]: k, n }))
  }
  if (orderBy) {
    const dir = orderBy.order === 'asc' ? 1 : -1
    rows = [...rows].sort((a, b) => (String(a[orderBy.field] ?? '') > String(b[orderBy.field] ?? '') ? dir : -dir))
  }
  return rows.slice(limit_start, limit_start + limit)
}

// ---- Server methods the dashboard calls ----------------------------------------------------------

const today = () => ago(0).slice(0, 10)
const daysAgo = (n) => ago(n * 1440).slice(0, 10)

function setupStatus() {
  const ok = (detail) => ({ ok: true, detail })
  const enabledDest = db['Teams Destination'].filter((d) => d.enabled)
  const linked = db['Teams User Map'].filter((u) => u.user).length
  return {
    checks: {
      scheduler: ok('Scheduler is enabled.'),
      workers: ok("2 worker(s) listen on the 'teams' queue."),
      enabled: ok('Teams Notify is enabled.'),
      destination: ok(`${enabledDest.filter((d) => d.destination_type.startsWith('Webhook')).length} webhook and ${enabledDest.filter((d) => d.destination_type.startsWith('Bot')).length} bot destination(s) enabled.`),
      delivered: ok('Last delivery a few minutes ago.'),
      rule: ok(`${db['Notification Rule'].filter((r) => r.is_enabled).length} rule(s) enabled.`),
      bot_credentials: ok('App ID, Tenant ID and client secret are saved.'),
      bot_enabled: ok('Bot is enabled.'),
      public_https: ok('Site URL is public HTTPS.'),
      secret_expiry: ok('Secret expires in 214 days.'),
      users: ok(`${db['Teams User Map'].filter((u) => u.installed).length} Teams user(s) installed the app, ${linked} linked to a Frappe user.`),
    },
    site: 'erp.example.com',
    site_url: 'https://erp.example.com',
    messaging_endpoint: 'https://erp.example.com/api/method/notification_engine.teams.bot.endpoint.receive',
    queue: 'teams',
    bot_name: 'ERP Notifications',
    bot_enabled: true,
    bot_started: true,
    secret_days_left: 214,
    frappe_version: '15.98.1',
    app_version: '0.1.0',
    checked_at: ago(0),
  }
}

function overview() {
  const logs = db['Teams Message Log']
  const count = (status, since) => logs.filter((l) => l.status === status && l.creation >= since).length
  const weekStart = daysAgo(6)
  const sentWeek = count('Sent', weekStart)
  const failedWeek = count('Failed', weekStart)
  const daily = []
  for (let i = 13; i >= 0; i--) {
    const date = daysAgo(i)
    const day = logs.filter((l) => l.creation.startsWith(date))
    daily.push({
      date,
      sent: day.filter((l) => l.status === 'Sent').length,
      failed: day.filter((l) => l.status === 'Failed').length,
      other: day.filter((l) => !['Sent', 'Failed'].includes(l.status)).length,
    })
  }
  const dests = db['Teams Destination']
  return {
    kpis: {
      sent_today: count('Sent', today()),
      failed_today: count('Failed', today()),
      waiting: logs.filter((l) => ['Queued', 'Throttled'].includes(l.status)).length,
      success_rate_7d: sentWeek + failedWeek ? Math.round((1000 * sentWeek) / (sentWeek + failedWeek)) / 10 : null,
      active_rules: db['Notification Rule'].filter((r) => r.is_enabled).length,
      total_rules: db['Notification Rule'].length,
      active_destinations: dests.filter((d) => d.enabled).length,
      failing_destinations: dests.filter((d) => d.enabled && d.consecutive_failures > 0).length,
    },
    daily,
    destinations: [...dests].sort((a, b) => b.enabled - a.enabled || b.consecutive_failures - a.consecutive_failures || a.name.localeCompare(b.name)),
    failures: getList('Teams Message Log', { filters: [['status', '=', 'Failed']], orderBy: { field: 'modified', order: 'desc' }, limit: 8 }),
    setup: setupStatus(),
  }
}

let nextLog = 900000
function queueTest(destination, rule) {
  const now = ago(0)
  const title = rule ? `[TEST] ${rule.title}${rule.doc}00412` : '[TEST] Teams Notify test message'
  const log = {
    name: `TNL-${nextLog++}`, title, status: 'Queued', destination, rule: rule?.name || null,
    event: rule?.event || null, reference_doctype: rule?.document_type || null,
    reference_name: rule ? `${rule.doc}00412` : null, attempts: 0, http_status: null, error: null,
    is_test: 1, creation: now, modified: now, sent_at: null,
    payload: JSON.stringify({ type: 'message', attachments: [{ contentType: 'application/vnd.microsoft.card.adaptive', content: { type: 'AdaptiveCard', version: '1.4', body: [{ type: 'TextBlock', text: title, weight: 'Bolder' }] } }] }),
  }
  db['Teams Message Log'].unshift(log)
  later(1200, () => deliver(log))
  return log.name
}

function deliver(log) {
  const dest = db['Teams Destination'].find((d) => d.name === log.destination)
  log.attempts += 1
  log.modified = ago(0)
  if (dest?.consecutive_failures) {
    Object.assign(log, { status: 'Failed', http_status: 404, error: dest.last_error?.replace(/^HTTP 404: /, '') })
    dest.consecutive_failures += 1
    dest.last_error_at = ago(0)
  } else {
    Object.assign(log, { status: 'Sent', http_status: 200, error: null, sent_at: ago(0) })
    if (dest) dest.last_success = ago(0)
  }
}

const methods = {
  'notification_engine.teams.dashboard.get_overview': overview,
  'notification_engine.teams.dashboard.get_setup_status': setupStatus,
  'notification_engine.teams.api.check_bot_connection': () => 'Connected: Microsoft issued a token for this bot. (demo)',
  'notification_engine.teams.api.send_test_to_destination': ({ destination }) => queueTest(destination),
  'notification_engine.teams.api.send_test_for_rule': ({ rule }) => {
    const r = db['Notification Rule'].find((x) => x.name === rule)
    return { condition: true, docname: `${r.doc}00412`, logs: r.destinations.map((d) => queueTest(d, r)) }
  },
  'notification_engine.teams.api.get_log_status': ({ names }) =>
    JSON.parse(names).map((n) => db['Teams Message Log'].find((l) => l.name === n)).filter(Boolean)
      .map(({ name, status, destination, error }) => ({ name, status, destination, error })),
  'notification_engine.teams.api.resend': ({ names }) => {
    const logs = JSON.parse(names).map((n) => db['Teams Message Log'].find((l) => l.name === n)).filter(Boolean)
    logs.forEach((l) => { l.status = 'Queued'; l.error = null })
    changed()
    logs.forEach((l, i) => later(1000 + i * 300, () => deliver(l)))
    return logs.length
  },
}

function runMethod(method, args = {}) {
  const fn = methods[method]
  if (!fn) return Promise.reject({ message: `${method} is not available in the demo.` })
  try {
    return respond(fn(args))
  } catch (e) {
    return Promise.reject({ message: String(e) })
  }
}

// ---- frappe-react-sdk API ----------------------------------------------------------------------

const call = { get: runMethod, post: runMethod, put: runMethod, delete: runMethod }
export const FrappeContext = createContext({ call })

// Shows "loading" briefly on first render, like a real request, then serves from memory.
function useResult(compute, deps) {
  const v = useVersion()
  const [ready, setReady] = useState(false)
  useEffect(() => { const t = setTimeout(() => setReady(true), 200); return () => clearTimeout(t) }, [])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const data = useMemo(() => (ready ? compute() : undefined), [ready, v, ...deps])
  const mutate = useCallback(() => { changed(); return Promise.resolve() }, [])
  return { data, error: null, isLoading: !ready, isValidating: false, mutate }
}

const key = (x) => JSON.stringify(x ?? null)

export const useFrappeGetCall = (method, params) =>
  useResult(() => ({ message: methods[method](params || {}) }), [method, key(params)])

export const useFrappeGetDocList = (doctype, args) =>
  useResult(() => getList(doctype, args).map((r) => ({ ...r })), [doctype, key(args)])

export const useFrappeGetDocCount = (doctype, filters) =>
  useResult(() => where(doctype, filters).length, [doctype, key(filters)])

export const useFrappeGetDoc = (doctype, name) =>
  useResult(() => ({ ...db[doctype].find((r) => r.name === name) }), [doctype, name])

export function useFrappeUpdateDoc() {
  const updateDoc = useCallback(async (doctype, name, patch) => {
    await new Promise((r) => setTimeout(r, 200))
    Object.assign(db[doctype].find((r) => r.name === name), patch, { modified: ago(0) })
    changed()
  }, [])
  return { updateDoc, loading: false, error: null }
}

// ---- Provider: demo banner and a notice for links into Frappe Desk ---------------------------------

export function FrappeProvider({ children }) {
  const [notice, setNotice] = useState(null)

  useEffect(() => {
    // Links to /app/... (Desk) and /api/... exist only on a real Frappe site.
    const onClick = (e) => {
      const a = e.target.closest?.('a[href]')
      const href = a?.getAttribute('href')
      if (!href || !/^\/(app|api)(\/|$)/.test(href)) return
      e.preventDefault()
      setNotice(href.startsWith('/api')
        ? 'Downloads and server actions need a real Frappe site.'
        : `On a real site this opens Frappe Desk (${href}).`)
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [])

  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), 4000)
    return () => clearTimeout(t)
  }, [notice])

  return (
    <FrappeContext.Provider value={{ call }}>
      <div className="bg-accent text-white text-[13px] px-4 py-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-center">
        <span><b>Live demo</b> with sample data. Nothing is sent to Microsoft Teams.</span>
        <a href={REPO} className="text-white underline font-medium">Install it on your Frappe site →</a>
      </div>
      {children}
      {notice && (
        <div role="status" className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 max-w-[calc(100%-32px)] card shadow-lg px-4 py-3 flex items-start gap-2 text-[13px]">
          <Info size={16} className="text-accent-text flex-none mt-0.5" />
          <span className="flex-1">{notice}</span>
          <button className="btn btn-ghost btn-sm" aria-label="Dismiss" onClick={() => setNotice(null)}><X size={14} /></button>
        </div>
      )}
    </FrappeContext.Provider>
  )
}
