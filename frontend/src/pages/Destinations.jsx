import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useFrappeGetDocList, useFrappeUpdateDoc } from 'frappe-react-sdk'
import { Bot, CheckCircle2, ExternalLink, Mail, Plus, Send, User, Webhook, XCircle } from 'lucide-react'
import { Empty, ErrorBox, Loading, PageHeader, Pill, Toggle } from '../components/ui.jsx'
import { useToast } from '../components/Toast.jsx'
import { dateTime, deskUrl, errorText, timeAgo } from '../lib/format.js'
import { useSendTestToDestination } from '../lib/actions.js'

const TYPES = {
  Webhook: { icon: Webhook, hint: 'Workflows webhook → chat or channel' },
  'Webhook (Personal via Flow bot)': { icon: User, hint: 'Workflows webhook → personal chat via Flow bot' },
  'Bot Conversation': { icon: Bot, hint: 'Bot → group chat or channel' },
  'Bot (Personal Chat)': { icon: Bot, hint: 'Bot → personal chats' },
}

export default function Destinations() {
  const { data, error, isLoading, mutate } = useFrappeGetDocList('Teams Destination', {
    fields: ['name', 'destination_type', 'enabled', 'conversation_type', 'conversation_name', 'installed_by', 'rate_per_second', 'burst', 'last_success', 'last_error_at', 'last_error', 'consecutive_failures'],
    orderBy: { field: 'creation', order: 'asc' },
    limit: 500,
  })
  const { updateDoc } = useFrappeUpdateDoc()
  const toast = useToast()
  const sendTest = useSendTestToDestination()
  const [busy, setBusy] = useState(null)

  const run = async (name, fn) => {
    setBusy(name)
    try { await fn() } finally { setBusy(null); mutate() }
  }
  const toggle = (name, enabled) =>
    run(name, async () => {
      try {
        await updateDoc('Teams Destination', name, { enabled: enabled ? 1 : 0 })
        toast(`${name} ${enabled ? 'enabled' : 'disabled'}.`)
      } catch (e) {
        toast(errorText(e), 'bad')
      }
    })

  const newBots = (data || []).filter((d) => !d.enabled && d.destination_type === 'Bot Conversation' && !d.last_success)

  return (
    <>
      <PageHeader
        title="Destinations"
        subtitle="Where messages go: Workflows webhooks and chats the bot was added to."
        actions={<a className="btn btn-primary" href={deskUrl('Teams Destination') + '/new'}><Plus size={14} /> New webhook</a>}
      />
      <ErrorBox error={error && errorText(error)} />

      {newBots.length > 0 && (
        <div className="card bg-accent-soft border-accent! p-3 mb-4 text-[13px] flex gap-2 items-start">
          <Bot size={16} className="text-accent-text mt-0.5 flex-none" />
          <span>
            The bot was added to {newBots.length} chat(s) that are still off: <b>{newBots.map((d) => d.name).join(', ')}</b>.
            Turn them on to let rules post there.
          </span>
        </div>
      )}

      {isLoading ? <Loading /> : !data?.length ? (
        <div className="card">
          <Empty icon={Send} title="No destinations yet">
            Create a webhook destination, or add the Teams bot to a chat. <Link className="text-accent-text" to="/install">See the install guide.</Link>
          </Empty>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 gap-3">
          {data.map((d) => {
            const t = TYPES[d.destination_type] || TYPES.Webhook
            const failing = d.consecutive_failures > 0
            return (
              <article key={d.name} className={`card p-4 flex flex-col gap-3 ${d.enabled ? '' : 'opacity-75'}`}>
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-lg bg-accent-soft text-accent-text grid place-items-center flex-none"><t.icon size={18} /></div>
                  <div className="min-w-0 flex-1">
                    <a href={deskUrl('Teams Destination', d.name)} className="font-semibold text-ink hover:text-accent-text block truncate">{d.name}</a>
                    <div className="text-[12px] text-ink-3">{d.destination_type} · {t.hint}</div>
                  </div>
                  <Toggle checked={!!d.enabled} disabled={busy === d.name} label={`Enable ${d.name}`} onChange={(v) => toggle(d.name, v)} />
                </div>

                <div className="text-[13px] flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    {!d.enabled ? <Pill>Off</Pill> : failing ? <Pill tone="bad"><XCircle size={12} /> {d.consecutive_failures} failures in a row</Pill>
                      : d.last_success ? <Pill tone="good"><CheckCircle2 size={12} /> Healthy</Pill> : <Pill tone="warn">Not tested</Pill>}
                    {d.last_success && <span className="text-ink-2" title={dateTime(d.last_success)}>Last delivered {timeAgo(d.last_success)}</span>}
                  </div>
                  {failing && d.last_error && <div className="text-bad-text line-clamp-2" title={d.last_error}>{d.last_error}</div>}
                  {d.conversation_name && <div className="text-ink-2">Chat: {d.conversation_name}{d.installed_by ? ` · added by ${d.installed_by}` : ''}</div>}
                  {(d.rate_per_second || d.burst) ? <div className="text-ink-3">Rate limit override: {d.rate_per_second || 'default'}/s, burst {d.burst || 'default'}</div> : null}
                </div>

                <div className="flex gap-2 mt-auto">
                  <button className="btn btn-sm" disabled={!d.enabled || busy === d.name} onClick={() => run(d.name, () => sendTest(d.name))}
                    title={d.enabled ? 'Send a [TEST] card' : 'Turn the destination on first'}>
                    <Send size={13} /> Send test
                  </button>
                  <Link className="btn btn-sm" to={`/messages?destination=${encodeURIComponent(d.name)}`}><Mail size={13} /> Messages</Link>
                  <a className="btn btn-sm ml-auto" href={deskUrl('Teams Destination', d.name)}><ExternalLink size={13} /> Edit</a>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </>
  )
}
