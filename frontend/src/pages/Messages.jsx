import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useFrappeGetDoc, useFrappeGetDocCount, useFrappeGetDocList } from 'frappe-react-sdk'
import { ChevronLeft, ChevronRight, ExternalLink, Inbox, RefreshCw, RotateCcw, Search, X } from 'lucide-react'
import { Card, Empty, ErrorBox, Loading, PageHeader, Pill, StatusBadge } from '../components/ui.jsx'
import { dateTime, deskUrl, errorText, timeAgo } from '../lib/format.js'
import { useResend } from '../lib/actions.js'

const STATUSES = ['', 'Sent', 'Failed', 'Queued', 'Throttled', 'Skipped']
const PAGE = 25

export default function Messages() {
  const [params, setParams] = useSearchParams()
  const status = params.get('status') || ''
  const destination = params.get('destination') || ''
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState([])
  const [open, setOpen] = useState(null)
  const resend = useResend()

  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])
  useEffect(() => { setPage(0); setSelected([]) }, [status, destination, query])

  const filters = useMemo(() => {
    const f = []
    if (status) f.push(['status', '=', status])
    if (destination) f.push(['destination', '=', destination])
    if (query) f.push(['title', 'like', `%${query}%`])
    return f
  }, [status, destination, query])

  const { data, error, isLoading, mutate, isValidating } = useFrappeGetDocList('Teams Message Log', {
    fields: ['name', 'title', 'status', 'destination', 'rule', 'reference_doctype', 'reference_name', 'attempts', 'http_status', 'is_test', 'creation', 'sent_at', 'error'],
    filters,
    orderBy: { field: 'creation', order: 'desc' },
    limit: PAGE,
    limit_start: page * PAGE,
  })
  const { data: count, mutate: mutateCount } = useFrappeGetDocCount('Teams Message Log', filters)
  const { data: dests } = useFrappeGetDocList('Teams Destination', { fields: ['name'], limit: 200, orderBy: { field: 'name', order: 'asc' } })

  const setFilter = (key, value) => {
    const next = new URLSearchParams(params)
    value ? next.set(key, value) : next.delete(key)
    setParams(next, { replace: true })
  }
  const refresh = () => { mutate(); mutateCount() }
  const resendable = (data || []).filter((r) => r.status !== 'Queued')
  const allSelected = resendable.length > 0 && resendable.every((r) => selected.includes(r.name))
  const pages = Math.max(1, Math.ceil((count || 0) / PAGE))

  return (
    <>
      <PageHeader
        title="Message Log"
        subtitle="Every message Teams Notify queued, with its delivery result."
        actions={
          <>
            {selected.length > 0 && (
              <button className="btn btn-primary" onClick={() => resend(selected).then(() => { setSelected([]); refresh() })}>
                <RotateCcw size={14} /> Resend {selected.length}
              </button>
            )}
            <button className="btn" onClick={refresh} disabled={isValidating}>
              <RefreshCw size={14} className={isValidating ? 'spin' : ''} /> Refresh
            </button>
          </>
        }
      />

      <div className="flex flex-wrap gap-2 mb-3">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search size={14} className="absolute left-2.5 top-2.5 text-ink-3" />
          <input className="input w-full pl-8" placeholder="Search titles" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className="input" value={status} onChange={(e) => setFilter('status', e.target.value)} aria-label="Status">
          {STATUSES.map((s) => <option key={s} value={s}>{s || 'All statuses'}</option>)}
        </select>
        <select className="input max-w-[220px]" value={destination} onChange={(e) => setFilter('destination', e.target.value)} aria-label="Destination">
          <option value="">All destinations</option>
          {(dests || []).map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
        </select>
      </div>

      <ErrorBox error={error && errorText(error)} />
      <Card bodyClass="p-0">
        {isLoading ? <Loading /> : !data?.length ? (
          <Empty icon={Inbox} title="No messages">Nothing matches these filters.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="w-8">
                    <input type="checkbox" aria-label="Select all" checked={allSelected}
                      onChange={() => setSelected(allSelected ? [] : resendable.map((r) => r.name))} />
                  </th>
                  <th>Message</th><th>Status</th><th>Destination</th><th>Document</th><th className="text-right">Tries</th><th>Created</th>
                </tr>
              </thead>
              <tbody>
                {data.map((r) => (
                  <tr key={r.name} className="cursor-pointer" onClick={() => setOpen(r.name)}>
                    <td onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Select ${r.title}`} disabled={r.status === 'Queued'}
                        checked={selected.includes(r.name)}
                        onChange={(e) => setSelected((s) => e.target.checked ? [...s, r.name] : s.filter((x) => x !== r.name))} />
                    </td>
                    <td className="max-w-[300px]">
                      <div className="font-medium truncate">{r.is_test ? <Pill tone="accent">Test</Pill> : null} {r.title || r.name}</div>
                      {r.status === 'Failed' && r.error && <div className="text-[12px] text-bad-text truncate">{r.error}</div>}
                      {r.status !== 'Failed' && r.rule && <div className="text-[12px] text-ink-3 truncate">{r.rule}</div>}
                    </td>
                    <td><StatusBadge status={r.status} /></td>
                    <td className="whitespace-nowrap">{r.destination}</td>
                    <td className="whitespace-nowrap text-ink-2">{r.reference_name ? `${r.reference_doctype} ${r.reference_name}` : '—'}</td>
                    <td className="text-right tabular-nums">{r.attempts}</td>
                    <td className="whitespace-nowrap text-ink-2" title={dateTime(r.creation)}>{timeAgo(r.creation)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-line text-[13px] text-ink-2">
          <span>{count ?? '…'} message(s)</span>
          <div className="flex items-center gap-2">
            <button className="btn btn-sm" aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></button>
            <span className="tabular-nums">Page {page + 1} of {pages}</span>
            <button className="btn btn-sm" aria-label="Next page" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></button>
          </div>
        </div>
      </Card>

      {open && <LogPanel name={open} onClose={() => setOpen(null)} onResent={refresh} />}
    </>
  )
}

function LogPanel({ name, onClose, onResent }) {
  const { data: log, error, isLoading, mutate } = useFrappeGetDoc('Teams Message Log', name)
  const resend = useResend()
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  let payload = log?.payload
  try { payload = JSON.stringify(JSON.parse(payload), null, 2) } catch { /* keep as is */ }

  const rows = log && [
    ['Destination', log.destination],
    ['Rule', log.rule],
    ['Event', log.event],
    ['Document', log.reference_name && `${log.reference_doctype} ${log.reference_name}`],
    ['Recipient', log.recipient_user || log.recipient_email],
    ['Attempts', log.attempts],
    ['HTTP status', log.http_status || null],
    ['Created', dateTime(log.creation)],
    ['Sent at', log.sent_at && dateTime(log.sent_at)],
    ['Next attempt', log.next_attempt_at && dateTime(log.next_attempt_at)],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '')

  return (
    <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose}>
      <aside
        className="absolute right-0 top-0 h-full w-full max-w-[560px] bg-surface border-l border-line overflow-y-auto"
        onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Message details"
      >
        <header className="flex items-center justify-between gap-3 px-5 py-4 border-b border-line sticky top-0 bg-surface">
          <div className="min-w-0">
            <div className="font-semibold truncate">{log?.title || name}</div>
            <div className="text-[12px] text-ink-3">{name}</div>
          </div>
          <button className="btn btn-ghost" aria-label="Close" onClick={onClose}><X size={18} /></button>
        </header>
        {isLoading ? <Loading /> : error ? <div className="p-5"><ErrorBox error={errorText(error)} /></div> : (
          <div className="p-5 flex flex-col gap-4">
            <div className="flex items-center gap-2 flex-wrap">
              <StatusBadge status={log.status} />
              {log.is_test ? <Pill tone="accent">Test</Pill> : null}
              <div className="ml-auto flex gap-2">
                {log.status !== 'Queued' && (
                  <button className="btn btn-sm" onClick={() => resend([name]).then(() => { mutate(); onResent() })}>
                    <RotateCcw size={13} /> Resend
                  </button>
                )}
                <a className="btn btn-sm" href={deskUrl('Teams Message Log', name)}><ExternalLink size={13} /> Open in Desk</a>
              </div>
            </div>
            {log.error && <div className="rounded-md bg-bad-soft text-bad-text p-3 text-[13px] whitespace-pre-wrap break-words">{log.error}</div>}
            <dl className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-2 m-0">
              {rows.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-ink-3 text-[13px]">{k}</dt>
                  <dd className="m-0 break-words">{v}</dd>
                </div>
              ))}
            </dl>
            {log.reference_name && (
              <a className="text-accent-text text-[13px]" href={deskUrl(log.reference_doctype, log.reference_name)}>Open {log.reference_doctype} {log.reference_name}</a>
            )}
            <div>
              <div className="text-[13px] font-semibold mb-1.5">Payload sent to Teams</div>
              <pre className="code m-0 max-h-[420px]">{payload || '—'}</pre>
            </div>
          </div>
        )}
      </aside>
    </div>
  )
}
