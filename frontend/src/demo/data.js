// Sample data for the public demo (`yarn build:demo`). Dates are relative to "now" so the demo
// always looks current. Values are formatted like Frappe's: "YYYY-MM-DD HH:mm:ss" in local time.

const pad = (n) => String(n).padStart(2, '0')
export const fmt = (d) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
export const ago = (minutes) => fmt(new Date(Date.now() - minutes * 60000))

// Deterministic pseudo-random numbers, so every visitor sees the same demo.
function rng(seed) {
  return () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296
    return seed / 4294967296
  }
}

export const destinations = [
  { name: 'Purchase team chat', destination_type: 'Webhook', enabled: 1, conversation_type: 'groupChat', creation: ago(60 * 24 * 40), last_success: ago(12), consecutive_failures: 0 },
  { name: 'Accounts → Payments', destination_type: 'Webhook', enabled: 1, conversation_type: 'channel', creation: ago(60 * 24 * 38), last_success: ago(95), consecutive_failures: 0, rate_per_second: 0.5, burst: 2 },
  { name: 'Personal (Flow bot)', destination_type: 'Webhook (Personal via Flow bot)', enabled: 1, creation: ago(60 * 24 * 30), last_success: ago(41), consecutive_failures: 0 },
  { name: 'OCTO Team (bot)', destination_type: 'Bot Conversation', enabled: 1, conversation_type: 'groupChat', conversation_name: 'OCTO Team', installed_by: 'Priya Nair', creation: ago(60 * 24 * 21), last_success: ago(7), consecutive_failures: 0 },
  { name: 'Teams Bot (Personal)', destination_type: 'Bot (Personal Chat)', enabled: 1, conversation_type: 'personal', creation: ago(60 * 24 * 21), last_success: ago(23), consecutive_failures: 0 },
  { name: 'HR announcements', destination_type: 'Webhook', enabled: 1, conversation_type: 'channel', creation: ago(60 * 24 * 60), last_success: ago(60 * 24 * 3), last_error_at: ago(180), consecutive_failures: 3, last_error: 'HTTP 404: The workflow was not found. It may have been deleted or turned off.' },
  { name: 'Sales team (bot)', destination_type: 'Bot Conversation', enabled: 0, conversation_type: 'groupChat', conversation_name: 'Sales team', installed_by: 'Arjun Mehta', creation: ago(60 * 5), consecutive_failures: 0 },
]

export const rules = [
  { send_teams: 1, send_email: 1, send_system_notification: 1, name: 'PO Approved → Purchase team', is_enabled: 1, reference_doctype: 'Purchase Order', event: 'Value Change', value_changed_field: 'workflow_state', condition: 'doc.workflow_state == "Approved"', teams_digest: 'None', teams_cooldown_minutes: 0, modified: ago(60 * 26), destinations: ['Purchase team chat'], doc: 'PUR-ORD-2026-', title: '✅ PO Approved: ' },
  { send_teams: 1, send_email: 0, send_system_notification: 0, name: 'PO Pending Approval → Approver', is_enabled: 1, reference_doctype: 'Purchase Order', event: 'Value Change', value_changed_field: 'workflow_state', condition: 'doc.workflow_state == "Pending Approval"', teams_digest: 'None', teams_cooldown_minutes: 0, modified: ago(60 * 50), destinations: ['OCTO Team (bot)', 'Teams Bot (Personal)'], doc: 'PUR-ORD-2026-', title: '🕒 Approval needed: ' },
  { send_teams: 1, send_email: 0, send_system_notification: 0, name: 'Payment Entry submitted', is_enabled: 1, reference_doctype: 'Payment Entry', event: 'On Submit', condition: 'doc.paid_amount > 100000', teams_digest: 'None', teams_cooldown_minutes: 0, modified: ago(60 * 24 * 4), destinations: ['Accounts → Payments'], doc: 'ACC-PAY-2026-', title: '💸 Payment made: ' },
  { send_teams: 1, send_email: 0, send_system_notification: 0, name: 'Overdue invoices (daily digest)', is_enabled: 1, reference_doctype: 'Sales Invoice', event: 'Days After', date_field: 'due_date', days_offset: 1, condition: 'doc.outstanding_amount > 0', teams_digest: 'Daily', teams_cooldown_minutes: 0, modified: ago(60 * 24 * 6), destinations: ['Accounts → Payments'], doc: 'ACC-SINV-2026-', title: '⚠️ Overdue: ' },
  { send_teams: 1, send_email: 0, send_system_notification: 0, name: 'New Lead → owner', is_enabled: 1, reference_doctype: 'Lead', event: 'After Insert', condition: '', teams_digest: 'None', teams_cooldown_minutes: 30, modified: ago(60 * 24 * 9), destinations: ['Personal (Flow bot)'], doc: 'CRM-LEAD-2026-', title: '👋 New lead: ' },
  { send_teams: 1, send_email: 1, send_system_notification: 0, name: 'Leave Application approved', is_enabled: 1, reference_doctype: 'Leave Application', event: 'Value Change', value_changed_field: 'status', condition: 'doc.status == "Approved"', teams_digest: 'None', teams_cooldown_minutes: 0, modified: ago(60 * 24 * 15), destinations: ['HR announcements'], doc: 'HR-LAP-2026-', title: '🌴 Leave approved: ' },
  { send_teams: 1, send_email: 0, send_system_notification: 0, name: 'Stock below reorder level', is_enabled: 0, reference_doctype: 'Bin', event: 'On Update', condition: 'doc.projected_qty < 10', teams_digest: 'Hourly', teams_cooldown_minutes: 0, modified: ago(60 * 24 * 20), destinations: ['Purchase team chat'], doc: 'BIN-', title: '📦 Low stock: ' },
]

export const users = [
  { name: 'TUM-0001', user: 'priya.nair@octoadvisory.com', teams_name: 'Priya Nair', teams_email: 'priya.nair@octoadvisory.com', installed: 1, last_seen: ago(7) },
  { name: 'TUM-0002', user: 'arjun.mehta@octoadvisory.com', teams_name: 'Arjun Mehta', teams_email: 'arjun.mehta@octoadvisory.com', installed: 1, last_seen: ago(60 * 3) },
  { name: 'TUM-0003', user: 'sara.fernandes@octoadvisory.com', teams_name: 'Sara Fernandes', teams_email: 'sara.fernandes@octoadvisory.com', installed: 1, last_seen: ago(60 * 26) },
  { name: 'TUM-0004', user: 'rahul.k@octoadvisory.com', teams_name: 'Rahul Kapoor', teams_email: 'rahul.k@octoadvisory.com', installed: 1, last_seen: ago(60 * 24 * 4) },
  { name: 'TUM-0005', user: null, teams_name: 'Neha (Contractor)', teams_email: 'neha@partner-firm.com', installed: 1, last_seen: ago(60 * 24 * 2) },
  { name: 'TUM-0006', user: 'vikram.s@octoadvisory.com', teams_name: 'Vikram Singh', teams_email: 'vikram.s@octoadvisory.com', installed: 0, last_seen: ago(60 * 24 * 12) },
]

const ERRORS = {
  404: 'The workflow was not found. It may have been deleted or turned off.',
  429: 'Too many requests. Retried with backoff.',
  502: 'Bad gateway from logic.azure.com.',
}

function card(title, docname, rule) {
  return JSON.stringify({
    type: 'message',
    attachments: [{
      contentType: 'application/vnd.microsoft.card.adaptive',
      contentUrl: null,
      content: {
        type: 'AdaptiveCard', version: '1.4',
        body: [
          { type: 'TextBlock', text: title, weight: 'Bolder', size: 'Medium', wrap: true },
          { type: 'FactSet', facts: [{ title: 'Document', value: docname }, { title: 'Rule', value: rule }] },
        ],
        actions: [{ type: 'Action.OpenUrl', title: 'Open in Frappe', url: `https://erp.example.com/app/${docname}` }],
      },
    }],
  })
}

// About two weeks of message history.
export function makeLogs() {
  const rand = rng(42)
  const logs = []
  const active = rules.filter((r) => r.is_enabled)
  let n = 1
  for (let day = 13; day >= 0; day--) {
    const count = Math.round(8 + rand() * 14 + (day % 7 < 2 ? -6 : 0))
    for (let i = 0; i < count; i++) {
      const rule = active[Math.floor(rand() * active.length)]
      const destination = rule.destinations[Math.floor(rand() * rule.destinations.length)]
      const minutes = day * 1440 + Math.floor(rand() * (day === 0 ? 600 : 1440))
      const docname = rule.doc + String(100 + Math.floor(rand() * 400)).padStart(5, '0')
      let status = 'Sent'
      let http_status = 200
      let error = null
      let attempts = 1
      if (destination === 'HR announcements' && day === 0) {
        status = 'Failed'; http_status = 404; error = ERRORS[404]; attempts = 1
      } else if (rand() < 0.04) {
        status = 'Failed'; http_status = rand() < 0.5 ? 502 : 429; error = ERRORS[http_status]; attempts = 6
      } else if (rand() < 0.08) {
        attempts = 2
      }
      const title = rule.title + docname
      logs.push({
        name: `TNL-${String(n++).padStart(6, '0')}`,
        title, status, destination, rule: rule.name,
        event: rule.event, reference_doctype: rule.document_type, reference_name: docname,
        attempts, http_status, error, is_test: 0,
        creation: ago(minutes), modified: ago(Math.max(0, minutes - 1)),
        sent_at: status === 'Sent' ? ago(Math.max(0, minutes - 1)) : null,
        payload: card(title, docname, rule.name),
      })
    }
  }
  // A couple waiting right now, so the queue counter isn't always zero.
  logs.push({ ...logs[logs.length - 1], name: `TNL-${String(n++).padStart(6, '0')}`, status: 'Throttled', sent_at: null, http_status: 429, error: ERRORS[429], attempts: 1, creation: ago(1), modified: ago(0) })
  return logs
}
