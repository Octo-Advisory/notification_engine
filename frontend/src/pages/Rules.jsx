import { useState } from 'react'
import { useFrappeGetDocList, useFrappeUpdateDoc } from 'frappe-react-sdk'
import { Pencil, Plus, Send, Workflow } from 'lucide-react'
import { Card, Empty, ErrorBox, Loading, PageHeader, Pill, Toggle } from '../components/ui.jsx'
import { useToast } from '../components/Toast.jsx'
import { deskUrl, errorText, timeAgo } from '../lib/format.js'
import { useSendTestForRule } from '../lib/actions.js'

const RULE = 'Notification Rule'
// One Notification Rule can send to several channels; this page lists the ones that include Teams.
const CHANNELS = [['send_email', 'Email'], ['send_system_notification', 'System'], ['send_sms', 'SMS']]

function describeEvent(r) {
  if (r.event === 'Value Change') return `When ${r.value_changed_field || 'a field'} changes`
  if (r.event === 'Days Before') return `${r.days_offset} day(s) before ${r.date_field}`
  if (r.event === 'Days After') return `${r.days_offset} day(s) after ${r.date_field}`
  return r.event
}

export default function Rules() {
  const { data, error, isLoading, mutate } = useFrappeGetDocList(RULE, {
    fields: ['name', 'is_enabled', 'reference_doctype', 'event', 'value_changed_field', 'date_field', 'days_offset', 'condition', 'teams_digest', 'teams_cooldown_minutes', 'send_email', 'send_system_notification', 'send_sms', 'modified'],
    filters: [['send_teams', '=', 1]],
    orderBy: { field: 'modified', order: 'desc' },
    limit: 500,
  })
  // Messages per rule in the last 7 days, for a quick "is it firing?" signal.
  const since = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10)
  const { data: counts } = useFrappeGetDocList('Teams Message Log', {
    fields: ['rule', 'count(name) as n'],
    filters: [['rule', 'is', 'set'], ['creation', '>=', since]],
    groupBy: 'rule',
    limit: 500,
  })
  const sent = Object.fromEntries((counts || []).map((c) => [c.rule, c.n]))

  const { updateDoc } = useFrappeUpdateDoc()
  const toast = useToast()
  const sendTest = useSendTestForRule()
  const [busy, setBusy] = useState(null)

  const toggle = async (rule, enabled) => {
    setBusy(rule)
    try {
      await updateDoc(RULE, rule, { is_enabled: enabled ? 1 : 0 })
      toast(`${rule} ${enabled ? 'enabled' : 'disabled'}.`)
      mutate()
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      setBusy(null)
    }
  }

  const test = async (rule) => {
    setBusy(rule)
    await sendTest(rule)
    setBusy(null)
  }

  return (
    <>
      <PageHeader
        title="Notification Rules"
        subtitle="Notification Rules with Microsoft Teams ticked: which document events send a Teams message, and where."
        actions={<a className="btn btn-primary" href={deskUrl(RULE) + '/new'}><Plus size={14} /> New rule</a>}
      />
      <ErrorBox error={error && errorText(error)} />
      <Card bodyClass="p-0">
        {isLoading ? <Loading /> : !data?.length ? (
          <Empty icon={Workflow} title="No rules yet">
            A Notification Rule picks a DocType and event, an optional condition and its recipients, then sends
            by Email, System notification, SMS and Teams at once. Tick <b>Microsoft Teams</b> on a rule to list it here.
            <div className="mt-3"><a className="btn btn-primary" href={deskUrl(RULE) + '/new'}><Plus size={14} /> Create the first rule</a></div>
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr><th className="w-12">On</th><th>Rule</th><th>Trigger</th><th>Delivery</th><th className="text-right">Msgs 7d</th><th /></tr>
              </thead>
              <tbody>
                {data.map((r) => (
                  <tr key={r.name}>
                    <td><Toggle checked={!!r.is_enabled} disabled={busy === r.name} label={`Enable ${r.name}`} onChange={(v) => toggle(r.name, v)} /></td>
                    <td className="max-w-[280px]">
                      <a href={deskUrl(RULE, r.name)} className="font-medium text-ink hover:text-accent-text">{r.name}</a>
                      <div className="text-[12px] text-ink-3">Edited {timeAgo(r.modified)}</div>
                    </td>
                    <td className="max-w-[320px]">
                      <div><span className="font-medium">{r.reference_doctype}</span> · {describeEvent(r)}</div>
                      {r.condition && <code className="text-[12px] text-ink-2 font-mono truncate block" title={r.condition}>if {r.condition}</code>}
                    </td>
                    <td className="whitespace-nowrap">
                      <div className="flex gap-1 flex-wrap">
                        {r.teams_digest && r.teams_digest !== 'None' ? <Pill tone="accent">{r.teams_digest} digest</Pill> : <Pill>Instant</Pill>}
                        {r.teams_cooldown_minutes ? <Pill>{r.teams_cooldown_minutes} min cooldown</Pill> : null}
                        {CHANNELS.filter(([f]) => r[f]).map(([f, label]) => <Pill key={f}>+ {label}</Pill>)}
                      </div>
                    </td>
                    <td className="text-right tabular-nums">{sent[r.name] || 0}</td>
                    <td className="whitespace-nowrap text-right">
                      <div className="inline-flex gap-1.5">
                        <button className="btn btn-sm" disabled={busy === r.name} onClick={() => test(r.name)} title="Render against the latest document and send with a [TEST] prefix">
                          <Send size={13} /> Test
                        </button>
                        <a className="btn btn-sm" href={deskUrl(RULE, r.name)}><Pencil size={13} /> Edit</a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="text-[12px] text-ink-3 mt-3">
        Rules are edited in Desk, where field pickers, template previews and validation live. <b>Test</b> renders the rule against the latest document of its DocType and sends it with a [TEST] prefix; the condition is reported but not applied.
      </p>
    </>
  )
}
