import { useEffect, useMemo, useRef, useState } from 'react'
import { shortDay } from '../lib/format.js'

// Stacked daily bars: Sent (good) at the base, Failed (critical) above, other statuses (muted) on top.
// Status colours are paired with legend labels and a tooltip, never colour alone.
const SERIES = [
  { key: 'sent', label: 'Sent', color: 'var(--good)' },
  { key: 'failed', label: 'Failed', color: 'var(--bad)' },
  { key: 'other', label: 'Queued / skipped', color: 'var(--muted-bar)' },
]

const H = 180
const PAD = { top: 12, right: 8, bottom: 24, left: 32 }
const GAP = 2 // surface gap between stacked segments

function niceMax(v) {
  if (v <= 4) return 4
  const p = Math.pow(10, Math.floor(Math.log10(v)))
  const m = [1, 2, 2.5, 5, 10].find((x) => x * p >= v)
  return m * p
}

export default function DailyChart({ data }) {
  const [hover, setHover] = useState(null)
  const [width, setWidth] = useState(320)
  const box = useRef(null)
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, Math.floor(e.contentRect.width))))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [])
  const max = useMemo(() => niceMax(Math.max(0, ...data.map((d) => d.sent + d.failed + d.other))), [data])
  const total = data.reduce((a, d) => a + d.sent + d.failed + d.other, 0)

  const innerW = width - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const step = innerW / data.length
  const barW = Math.max(6, Math.min(28, step * 0.6))
  const y = (v) => (v / max) * innerH
  const ticks = [0, max / 2, max]

  return (
    <div>
      <div className="flex flex-wrap gap-4 mb-2 text-[12px] text-ink-2" role="list" aria-label="Legend">
        {SERIES.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5" role="listitem">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: s.color }} /> {s.label}
          </span>
        ))}
      </div>
      <div className="relative w-full overflow-hidden" ref={box}>
        <svg width={width} height={H} role="img" aria-label={`Messages per day, last ${data.length} days, ${total} total`}>
          {ticks.map((t) => (
            <g key={t} transform={`translate(0, ${PAD.top + innerH - y(t)})`}>
              <line x1={PAD.left} x2={width - PAD.right} stroke="var(--border)" strokeDasharray={t ? '3 3' : undefined} />
              <text x={PAD.left - 6} y={4} textAnchor="end" fontSize="11" fill="var(--text-3)">{t}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = PAD.left + step * i + step / 2
            let base = PAD.top + innerH
            const segs = SERIES.filter((s) => d[s.key] > 0)
            return (
              <g key={d.date}>
                {segs.map((s, j) => {
                  const h = Math.max(2, y(d[s.key]) - (j > 0 ? GAP : 0))
                  const top = base - h - (j > 0 ? GAP : 0)
                  const isTop = j === segs.length - 1
                  base = top
                  return (
                    <path
                      key={s.key}
                      d={roundedTop(cx - barW / 2, top, barW, h, isTop ? Math.min(4, h) : 0)}
                      fill={s.color}
                      opacity={hover === null || hover === i ? 1 : 0.45}
                    />
                  )
                })}
                {(data.length - 1 - i) % Math.ceil(data.length / 7) === 0 && (
                  <text x={cx} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--text-3)">{shortDay(d.date)}</text>
                )}
                {/* Hit target: the whole column, larger than the bar */}
                <rect
                  x={cx - step / 2} y={PAD.top} width={step} height={innerH} fill="transparent"
                  onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
                />
              </g>
            )
          })}
        </svg>
        {hover !== null && (
          <Tooltip d={data[hover]} left={PAD.left + step * hover + step / 2} width={width} />
        )}
      </div>
    </div>
  )
}

function Tooltip({ d, left, width }) {
  const flip = left > width - 170
  return (
    <div
      className="absolute top-0 card shadow-md px-3 py-2 text-[12px] pointer-events-none min-w-[150px]"
      style={{ left: flip ? left - 160 : left + 12 }}
    >
      <div className="font-semibold mb-1">{shortDay(d.date)}</div>
      {SERIES.map((s) => (
        <div key={s.key} className="flex items-center gap-2 text-ink-2">
          <span className="w-2 h-2 rounded-sm" style={{ background: s.color }} />
          {s.label}
          <span className="ml-auto font-semibold text-ink tabular-nums">{d[s.key]}</span>
        </div>
      ))}
    </div>
  )
}

function roundedTop(x, y, w, h, r) {
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`
}
