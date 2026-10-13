import { useState } from 'react'
import { AlertTriangle, Check, CheckCircle2, CircleDashed, Clock, Copy, Loader2, MinusCircle, XCircle } from 'lucide-react'

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight m-0">{title}</h1>
        {subtitle && <p className="text-ink-2 mt-1 mb-0">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function Card({ title, actions, children, className = '', bodyClass = 'p-4' }) {
  return (
    <section className={`card min-w-0 ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-line">
          <h2 className="text-[14px] font-semibold m-0">{title}</h2>
          {actions}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  )
}

const STATUS = {
  Sent: { cls: 'bg-good-soft text-good-text', Icon: CheckCircle2 },
  Failed: { cls: 'bg-bad-soft text-bad-text', Icon: XCircle },
  Queued: { cls: 'bg-accent-soft text-accent-text', Icon: Clock },
  Throttled: { cls: 'bg-warn-soft text-warn-text', Icon: Clock },
  Skipped: { cls: 'bg-surface-2 text-ink-2', Icon: MinusCircle },
}

// Status always carries an icon and a label, never colour alone.
export function StatusBadge({ status }) {
  const s = STATUS[status] || STATUS.Skipped
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold ${s.cls}`}>
      <s.Icon size={13} aria-hidden /> {status}
    </span>
  )
}

export function Pill({ tone = 'neutral', children }) {
  const cls = {
    good: 'bg-good-soft text-good-text',
    bad: 'bg-bad-soft text-bad-text',
    warn: 'bg-warn-soft text-warn-text',
    accent: 'bg-accent-soft text-accent-text',
    neutral: 'bg-surface-2 text-ink-2',
  }[tone]
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold ${cls}`}>{children}</span>
}

// A setup check result: ok true / false, or null when it does not apply.
export function CheckPill({ check }) {
  if (!check) return <Pill><Loader2 size={12} className="spin" /> Checking</Pill>
  if (check.ok === null) return <Pill><CircleDashed size={12} /> Not used</Pill>
  return check.ok ? (
    <Pill tone="good"><Check size={12} strokeWidth={3} /> Done</Pill>
  ) : (
    <Pill tone="warn"><AlertTriangle size={12} /> To do</Pill>
  )
}

export function Toggle({ checked, onChange, disabled, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={!!checked}
      aria-label={label}
      className="toggle"
      disabled={disabled}
      onClick={() => onChange(!checked)}
    />
  )
}

export function CopyButton({ text, label = 'Copy', className = 'btn btn-sm' }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    }
    setDone(true)
    setTimeout(() => setDone(false), 1500)
  }
  return (
    <button type="button" className={className} onClick={copy}>
      {done ? <Check size={14} /> : <Copy size={14} />} {done ? 'Copied' : label}
    </button>
  )
}

export function CodeBlock({ children }) {
  const text = String(children).trim()
  return (
    <div className="relative group my-2">
      <pre className="code m-0 pr-20">{text}</pre>
      <div className="absolute top-2 right-2 opacity-80 group-hover:opacity-100">
        <CopyButton text={text} className="btn btn-sm" />
      </div>
    </div>
  )
}

export function Empty({ icon: Icon, title, children }) {
  return (
    <div className="flex flex-col items-center text-center py-10 px-4 text-ink-2">
      {Icon && <Icon size={28} className="text-ink-3 mb-2" />}
      <div className="font-semibold text-ink">{title}</div>
      {children && <div className="mt-1 max-w-md">{children}</div>}
    </div>
  )
}

export function Loading() {
  return (
    <div className="flex items-center justify-center py-16 text-ink-3">
      <Loader2 className="spin" size={22} />
    </div>
  )
}

export function ErrorBox({ error }) {
  if (!error) return null
  return (
    <div className="card border-bad! bg-bad-soft text-bad-text p-3 mb-4 flex gap-2 items-start">
      <XCircle size={16} className="mt-0.5 flex-none" /> <span>{error}</span>
    </div>
  )
}
