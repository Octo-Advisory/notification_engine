import { Link } from 'react-router-dom'
import { useFrappeGetCall } from 'frappe-react-sdk'
import { AlertTriangle, ArrowRight, BookOpen, CheckCircle2, Clock, RefreshCw, RotateCcw, Send, XCircle } from 'lucide-react'
import { Card, Empty, ErrorBox, Loading, PageHeader, Pill } from '../components/ui.jsx'
import DailyChart from '../components/DailyChart.jsx'
import { deskUrl, errorText, timeAgo } from '../lib/format.js'
import { useResend, useSendTestToDestination } from '../lib/actions.js'
import { CORE_CHECKS } from './InstallGuide.jsx'

function Stat({ label, value, hint, icon: Icon, tone }) {
  const toneCls = { good: 'text-good-text', bad: 'text-bad-text', accent: 'text-accent-text', neutral: 'text-ink-2' }[tone]
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 text-ink-2 text-[13px]">
        <Icon size={15} className={toneCls} aria-hidden /> {label}
      </div>
      <div className="text-[28px] font-semibold mt-1 tabular-nums leading-tight">{value}</div>
      {hint && <div className="text-[12px] text-ink-3 mt-0.5">{hint}</div>}
    </div>
  )
}

export default function Overview() {
  const { data, error, isLoading, mutate, isValidating } = useFrappeGetCall(
    'notification_engine.teams.dashboard.get_overview', undefined, 'overview', { refreshInterval: 30000 }
  )
  const resend = useResend()
  const sendTest = useSendTestToDestination()

  if (isLoading) return <Loading />
  if (error) return <ErrorBox error={errorText(error)} />
  const { kpis, daily, destinations, failures, setup } = data.message
  const core = CORE_CHECKS.map((k) => setup.checks[k])
  const done = core.filter((c) => c.ok).length

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle={`Delivery health for ${setup.site}`}
        actions={
          <button className="btn" onClick={() => mutate()} disabled={isValidating}>
            <RefreshCw size={14} className={isValidating ? 'spin' : ''} /> Refresh
          </button>
        }
      />

      {done < core.length && (
        <Link to="/install" className="card flex items-center gap-3 p-4 mb-5 no-underline text-ink hover:border-accent">
          <div className="w-9 h-9 rounded-lg bg-accent-soft text-accent-text grid place-items-center flex-none">
            <BookOpen size={18} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-semibold">Finish setting up Teams Notify</div>
            <div className="text-ink-2 text-[13px]">{done} of {core.length} setup steps done. The install guide checks each one live.</div>
            <div className="h-1.5 rounded-full bg-surface-2 mt-2 overflow-hidden">
              <div className="h-full bg-accent rounded-full" style={{ width: `${(100 * done) / core.length}%` }} />
            </div>
          </div>
          <ArrowRight size={18} className="text-ink-3" />
        </Link>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <Stat label="Sent today" value={kpis.sent_today} icon={CheckCircle2} tone="good" />
        <Stat label="Failed today" value={kpis.failed_today} icon={XCircle} tone={kpis.failed_today ? 'bad' : 'neutral'} />
        <Stat label="Waiting in queue" value={kpis.waiting} icon={Clock} tone="accent" hint="Queued or throttled" />
        <Stat
          label="Success rate, 7 days"
          value={kpis.success_rate_7d === null ? '—' : `${kpis.success_rate_7d}%`}
          icon={Send}
          tone="neutral"
          hint={`${kpis.active_rules}/${kpis.total_rules} rules · ${kpis.active_destinations} destinations on`}
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-4 mb-4">
        <Card title="Messages per day" className="lg:col-span-2" actions={<span className="text-[12px] text-ink-3">Last 14 days</span>}>
          <DailyChart data={daily} />
        </Card>

        <Card title="Destinations" bodyClass="p-0" actions={<Link to="/destinations" className="text-[13px] text-accent-text">All</Link>}>
          {destinations.length === 0 ? (
            <Empty icon={Send} title="No destinations yet">
              <Link to="/install" className="text-accent-text">Follow the install guide</Link> to add one.
            </Empty>
          ) : (
            <ul className="m-0 p-0 list-none max-h-[280px] overflow-y-auto">
              {destinations.map((d) => (
                <li key={d.name} className="flex items-center gap-3 px-4 py-2.5 border-b border-line last:border-0">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium truncate">{d.name}</div>
                    <div className="text-[12px] text-ink-3 truncate">
                      {d.consecutive_failures
                        ? `${d.consecutive_failures} failures in a row`
                        : d.last_success ? `Delivered ${timeAgo(d.last_success)}` : 'Never delivered'}
                    </div>
                  </div>
                  {!d.enabled ? (
                    <Pill>Off</Pill>
                  ) : d.consecutive_failures ? (
                    <Pill tone="bad"><XCircle size={12} /> Failing</Pill>
                  ) : d.last_success ? (
                    <Pill tone="good"><CheckCircle2 size={12} /> OK</Pill>
                  ) : (
                    <button className="btn btn-sm" onClick={() => sendTest(d.name).then(() => mutate())}>Test</button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card
        title="Recent failures"
        bodyClass="p-0"
        actions={<Link to="/messages?status=Failed" className="text-[13px] text-accent-text">All failures</Link>}
      >
        {failures.length === 0 ? (
          <Empty icon={CheckCircle2} title="No failed messages">Every message that finished was delivered.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr><th>Message</th><th>Destination</th><th>Error</th><th>When</th><th /></tr>
              </thead>
              <tbody>
                {failures.map((f) => (
                  <tr key={f.name}>
                    <td className="max-w-[260px]">
                      <a href={deskUrl('Teams Message Log', f.name)} className="font-medium text-ink hover:text-accent-text truncate block">{f.title || f.name}</a>
                      {f.rule && <div className="text-[12px] text-ink-3 truncate">{f.rule}</div>}
                    </td>
                    <td className="whitespace-nowrap">{f.destination}</td>
                    <td className="max-w-[320px]">
                      <div className="flex gap-1.5 items-start text-bad-text text-[13px]">
                        <AlertTriangle size={13} className="mt-0.5 flex-none" />
                        <span className="line-clamp-2">{f.http_status ? `HTTP ${f.http_status}: ` : ''}{f.error}</span>
                      </div>
                    </td>
                    <td className="whitespace-nowrap text-ink-2">{timeAgo(f.modified)}</td>
                    <td className="text-right">
                      <button className="btn btn-sm" onClick={() => resend([f.name]).then(() => mutate())}>
                        <RotateCcw size={13} /> Resend
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
