import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useFrappeGetCall } from 'frappe-react-sdk'
import { Bot, Download, ExternalLink, PlugZap, RefreshCw, Webhook } from 'lucide-react'
import { CheckPill, CodeBlock, CopyButton, ErrorBox, PageHeader, Pill } from '../components/ui.jsx'
import { useToast } from '../components/Toast.jsx'
import { deskUrl, errorText, timeAgo } from '../lib/format.js'
import { useCall } from '../lib/actions.js'

// Checks every installation needs, whichever delivery method is used. The Overview banner counts these.
export const CORE_CHECKS = ['scheduler', 'workers', 'enabled', 'destination', 'rule', 'delivered']

const SECTIONS = [
  { id: 'requirements', title: 'Before you start' },
  { id: 'install', title: 'Install the app' },
  { id: 'workers', title: 'Workers and scheduler' },
  { id: 'enable', title: 'Turn on Teams Notify' },
  { id: 'method', title: 'Choose a delivery method' },
  { id: 'webhook', title: 'Webhook setup', sub: true },
  { id: 'bot', title: 'Teams bot setup', sub: true },
  { id: 'rule', title: 'Create your first rule' },
  { id: 'verify', title: 'Check it end to end' },
  { id: 'production', title: 'Production checklist' },
  { id: 'troubleshooting', title: 'Troubleshooting' },
  { id: 'dashboard', title: 'Building this dashboard' },
]

function Step({ id, n, title, checks = [], children }) {
  return (
    <section id={id} className="card p-5 scroll-mt-6">
      <header className="flex flex-wrap items-start gap-3 mb-2">
        {n && <div className="w-7 h-7 rounded-full bg-accent text-white grid place-items-center text-[13px] font-semibold flex-none">{n}</div>}
        <h2 className="text-[17px] font-semibold m-0 flex-1 min-w-[200px] leading-7">{title}</h2>
      </header>
      {checks.length > 0 && (
        <ul className="list-none m-0 mb-3 p-0 flex flex-col gap-1.5">
          {checks.map(([label, check]) => (
            <li key={label} className="flex flex-wrap items-center gap-2 text-[13px] rounded-md bg-surface-2 px-3 py-2">
              <CheckPill check={check} />
              <span className="font-medium">{label}</span>
              {check && <span className="text-ink-2">— {check.detail}</span>}
            </li>
          ))}
        </ul>
      )}
      <div className="prose-guide">{children}</div>
    </section>
  )
}

function SubStep({ title, children }) {
  return (
    <div className="mt-5">
      <h3 className="text-[14px] font-semibold m-0 mb-1">{title}</h3>
      {children}
    </div>
  )
}

const Desk = ({ to, children }) => <a href={to}>{children}</a>

export default function InstallGuide() {
  const { data, error, isValidating, mutate } = useFrappeGetCall(
    'notification_engine.teams.dashboard.get_setup_status', undefined, 'setup-status'
  )
  const s = data?.message
  const c = (key) => s?.checks?.[key]
  const site = s?.site || '<your-site>'
  const call = useCall()
  const toast = useToast()
  const { hash } = useLocation()
  const [method, setMethod] = useState('webhook')
  const [checkingBot, setCheckingBot] = useState(false)

  useEffect(() => {
    if (hash === '#bot') setMethod('bot')
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [hash])

  const core = CORE_CHECKS.map(c)
  const done = core.filter((x) => x?.ok).length

  const checkBot = async () => {
    setCheckingBot(true)
    try {
      const r = await call.post('notification_engine.teams.api.check_bot_connection', {})
      toast(r.message, 'good')
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      setCheckingBot(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Install Guide"
        subtitle="Set up Teams Notify from a fresh bench to the first card in Teams. Steps with a status are checked live against this site."
        actions={
          <button className="btn" onClick={() => mutate()} disabled={isValidating}>
            <RefreshCw size={14} className={isValidating ? 'spin' : ''} /> Re-check
          </button>
        }
      />
      <ErrorBox error={error && errorText(error)} />

      <div className="card p-4 mb-5 flex flex-wrap items-center gap-4">
        <div className="flex-1 min-w-[220px]">
          <div className="font-semibold">{done} of {CORE_CHECKS.length} core steps done on {site}</div>
          <div className="h-2 rounded-full bg-surface-2 mt-2 overflow-hidden">
            <div className="h-full bg-accent rounded-full transition-all" style={{ width: `${(100 * done) / CORE_CHECKS.length}%` }} />
          </div>
        </div>
        {s && <div className="text-[12px] text-ink-3">Notification Engine {s.app_version} · Frappe {s.frappe_version} · checked {timeAgo(s.checked_at)}</div>}
      </div>

      <div className="lg:grid lg:grid-cols-[1fr_200px] gap-6 items-start">
        <div className="flex flex-col gap-4 min-w-0">
          <Step id="requirements" title="Before you start">
            <p>You need:</p>
            <ul>
              <li><b>Frappe v15 or v16</b> (ERPNext optional) on a bench you can run commands on, Python 3.10+.</li>
              <li><b>Node 18+ and yarn</b> to build this dashboard (<span className="kbd">bench build</span> does it for you).</li>
              <li><b>Microsoft 365 with Teams</b>, and an account allowed to create Workflows (Power Automate) for the webhook method.</li>
              <li>For the <b>Teams bot</b> method only: an Azure subscription, permission to register an app in Microsoft Entra ID, a Teams admin to upload the app, and a <b>public HTTPS address</b> for this site.</li>
            </ul>
            <p>Not sure which method you need? Read <a href="#method">step 5</a> first. Most teams start with the webhook and add the bot later.</p>
          </Step>

          <Step id="install" n={1} title="Install the app on your bench"
            checks={[['App installed', s && { ok: true, detail: `Notification Engine ${s.app_version} runs on ${site}.` }]]}>
            <p>Teams is part of the Notification Engine app. From the bench folder, fetch the app, install it on the site and build its assets:</p>
            <CodeBlock>{`cd ~/frappe-bench
bench get-app https://github.com/Octo-Advisory/notification_engine.git
bench --site ${site} install-app notification_engine
bench --site ${site} migrate
bench build --app notification_engine`}</CodeBlock>
            <p>Moving from the standalone <span className="kbd">teams_notify</span> app? Run <span className="kbd">{`bench --site ${site} remove-from-installed-apps teams_notify`}</span> first (its data stays), then migrate: destinations, settings, logs and rules are taken over.</p>
            <p>Then restart so web workers and background workers load the new code:</p>
            <CodeBlock>{`# production (supervisor)
sudo supervisorctl restart all

# development: stop and start again
bench start`}</CodeBlock>
            <p>Installing creates the <b>Teams Admin</b> role and an internal bot user. Give <b>Teams Admin</b> to anyone who should manage rules and destinations (System Managers already have access).</p>
            <p>On <b>Frappe Cloud</b>: add the app from its repository in your bench group, deploy, then install it on the site from the dashboard.</p>
          </Step>

          <Step id="workers" n={2} title="Background workers and scheduler"
            checks={[['Scheduler', c('scheduler')], ['Workers', c('workers')]]}>
            <p>Messages are sent from background workers, never during the user's save. The scheduler retries throttled or failed messages every minute and runs digests, date rules and log clean-up.</p>
            <CodeBlock>{`bench --site ${site} enable-scheduler
bench --site ${site} scheduler status`}</CodeBlock>
            <p><b>Optional, recommended for busy sites:</b> a dedicated <span className="kbd">teams</span> queue, so Teams messages never wait behind long reports. Add to <span className="kbd">sites/common_site_config.json</span>:</p>
            <CodeBlock>{`"workers": {
  "teams": { "timeout": 300 }
}`}</CodeBlock>
            <p>Then <span className="kbd">bench setup supervisor</span> and reload supervisor (production), or add <span className="kbd">worker_teams: bench worker --queue teams</span> to the <span className="kbd">Procfile</span> (development). Until a <span className="kbd">teams</span> worker exists, messages use the <span className="kbd">default</span> queue{s ? ` (now: ${s.queue})` : ''}.</p>
          </Step>

          <Step id="enable" n={3} title="Turn on Teams Notify" checks={[['Teams Notify enabled', c('enabled')]]}>
            <ol>
              <li>Open <Desk to="/app/teams-settings">Teams Settings</Desk> and tick <b>Enabled</b>. This is the global switch for every rule.</li>
              <li>Leave the defaults unless you have a reason to change them:
                <ul>
                  <li><b>Default Rate per Second</b> / <b>Default Burst</b>: how fast one destination is sent to. Workflows webhooks throttle at about 4 requests per second, and Teams posts slowly in a chat, so keep this low.</li>
                  <li><b>Max Retries</b>: retries on HTTP 429, 5xx and timeouts (5 s, 30 s, 2 min, 10 min, 1 h).</li>
                  <li><b>Failure Alert Threshold</b>: Teams Admins get a notification after this many failures in a row on one destination.</li>
                  <li><b>Log Retention Days</b>: older Message Logs are deleted daily.</li>
                  <li><b>Site URL</b>: only if "Open in Frappe" links must use a different address than this site's (for example a public domain).</li>
                </ul>
              </li>
              <li>Save.</li>
            </ol>
          </Step>

          <Step id="method" n={4} title="Choose a delivery method"
            checks={[['A destination is enabled', c('destination')]]}>
            <p>Teams Notify can send through either method, or both at once. Each destination uses one.</p>
            <div className="overflow-x-auto my-3">
              <table className="tbl text-[13px] border border-line rounded-md">
                <thead><tr><th /><th>Workflows webhook</th><th>Teams bot</th></tr></thead>
                <tbody>
                  <tr><td className="font-medium">Setup</td><td>10 minutes, inside Teams</td><td>Azure Bot + Entra app + Teams app upload</td></tr>
                  <tr><td className="font-medium">Public HTTPS URL for Frappe</td><td>Not needed</td><td>Required</td></tr>
                  <tr><td className="font-medium">Group chats and channels</td><td>Yes</td><td>Yes (add the bot to the chat)</td></tr>
                  <tr><td className="font-medium">Personal messages</td><td>Yes, through the Flow bot</td><td>Yes, from your own branded bot</td></tr>
                  <tr><td className="font-medium">Approve / Reject buttons</td><td>No</td><td>Yes, acting as the person who clicks</td></tr>
                  <tr><td className="font-medium">Posted as</td><td>The Workflows / Flow bot</td><td>Your bot's name and icon</td></tr>
                </tbody>
              </table>
            </div>
            <div className="flex gap-2 mt-3" role="tablist">
              <button role="tab" aria-selected={method === 'webhook'} className={`btn ${method === 'webhook' ? 'btn-primary' : ''}`} onClick={() => setMethod('webhook')}>
                <Webhook size={14} /> Webhook steps
              </button>
              <button role="tab" aria-selected={method === 'bot'} className={`btn ${method === 'bot' ? 'btn-primary' : ''}`} onClick={() => setMethod('bot')}>
                <Bot size={14} /> Teams bot steps
              </button>
            </div>
          </Step>

          {method === 'webhook' ? (
            <Step id="webhook" n="4a" title="Webhook: post to a chat or channel through Workflows"
              checks={[['Message delivered', c('delivered')]]}>
              <p>Office 365 Connectors (the old "Incoming Webhook") are retired. Teams Notify uses a <b>Workflows</b> webhook instead. Create it with a shared service account if you can, so it keeps working when a person leaves.</p>
              <SubStep title="1. Create the workflow in Teams">
                <ol>
                  <li>In Teams, open the chat or channel that should receive messages.</li>
                  <li>Open <b>⋯ → Workflows</b> (on a channel: <b>⋯ → Workflows</b> next to the channel name).</li>
                  <li>Pick the template <b>Send webhook alerts to a chat</b> (or <b>… to a channel</b>), name it, for example <i>ERP alerts</i>, and confirm the chat or channel.</li>
                  <li>Click <b>Add workflow</b> and <b>copy the URL</b> it shows. Treat it like a password: anyone with it can post to that chat.</li>
                </ol>
                <p>Building it yourself in Power Automate instead? Trigger <b>When a Teams webhook request is received</b> (Who can trigger: <b>Anyone</b>), then <b>Post card in a chat or channel</b> with Adaptive Card:</p>
                <CodeBlock>{`triggerBody()?['attachments'][0]['content']`}</CodeBlock>
              </SubStep>
              <SubStep title="2. Add it as a destination in Frappe">
                <ol>
                  <li>Open <Desk to={deskUrl('Teams Destination') + '/new'}>New Teams Destination</Desk>.</li>
                  <li><b>Destination Name</b>: e.g. <i>Sales team chat</i>. <b>Type</b>: <b>Webhook</b>. Paste the URL in <b>Webhook URL</b> (stored encrypted, never shown again). Tick <b>Enabled</b> and save.</li>
                  <li>On <Link to="/destinations">Destinations</Link>, click <b>Send test</b>. A <i>[TEST] Teams Notify test message</i> card should arrive within seconds.</li>
                </ol>
              </SubStep>
              <SubStep title="3. Optional: personal messages through the Flow bot">
                <p>To message individual people (e.g. the document owner) without the bot, create a second flow in Power Automate:</p>
                <ol>
                  <li>Trigger <b>When a Teams webhook request is received</b>, Who can trigger: <b>Anyone</b>.</li>
                  <li>Action <b>Post card in a chat or channel</b>: Post as <b>Flow bot</b>, Post in <b>Chat with Flow bot</b>.</li>
                  <li>Recipient: <span className="kbd">triggerBody()?['recipient']</span> · Adaptive Card: <span className="kbd">triggerBody()?['attachments'][0]['content']</span></li>
                  <li>Save, copy the URL into a Teams Destination of type <b>Webhook (Personal via Flow bot)</b>.</li>
                  <li>On a rule, add <b>Recipients</b> (Owner, Role, User, Assigned To, Document Field) and choose this destination as the <b>Personal Destination</b>.</li>
                </ol>
              </SubStep>
            </Step>
          ) : (
            <Step id="bot" n="4b" title="Teams bot: Azure Bot, Entra app and Teams app"
              checks={[
                ['Public HTTPS address', c('public_https')],
                ['Bot credentials saved', c('bot_credentials')],
                ['Bot enabled', c('bot_enabled')],
                ['Secret expiry reminder', c('secret_expiry')],
                ['Teams users linked', c('users')],
              ]}>
              <p>Steps 2 and 3 are done in the Azure portal, usually by IT. Everything else is in Frappe and Teams.</p>

              <SubStep title="1. Give this site a public HTTPS address">
                <p>Microsoft Teams calls the bot endpoint on this site, so it must be reachable from the internet over HTTPS (port 443, valid certificate). If users reach Frappe on another address than this site's, enter the public one as <b>Site URL</b> in <Desk to="/app/teams-settings">Teams Settings</Desk>.</p>
                <p>Your bot's messaging endpoint:</p>
                <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 my-2">
                  <code className="font-mono text-[12.5px] break-all flex-1 min-w-0">{s?.messaging_endpoint || '…'}</code>
                  {s && <CopyButton text={s.messaging_endpoint} />}
                </div>
                <p>For testing only, a temporary tunnel works (the repository's <span className="kbd">docs/BOT_TUNNEL_SETUP.md</span> shows Cloudflare quick tunnels). Its URL changes on every start.</p>
              </SubStep>

              <SubStep title="2. Register the app in Microsoft Entra ID">
                <ol>
                  <li>Azure portal → <b>Microsoft Entra ID → App registrations → New registration</b>.</li>
                  <li>Name it (e.g. <i>ERP Notifications</i>), <b>Supported account types</b>: <b>Single tenant</b>. No redirect URI. Register.</li>
                  <li>Copy the <b>Application (client) ID</b> and the <b>Directory (tenant) ID</b>.</li>
                  <li><b>Certificates &amp; secrets → New client secret</b>. Copy the secret's <b>Value</b> right away (not the Secret ID), and note its <b>expiry date</b>.</li>
                </ol>
              </SubStep>

              <SubStep title="3. Create the Azure Bot">
                <ol>
                  <li>Azure portal → <b>Create a resource → Azure Bot</b>.</li>
                  <li><b>Type of App</b>: <b>Single Tenant</b>. <b>Creation type</b>: <b>Use existing app registration</b>, with the App ID and Tenant ID from step 2. The free pricing tier is enough for Teams.</li>
                  <li>Open the bot → <b>Settings → Configuration</b>. Paste the <b>messaging endpoint</b> above and <b>Apply</b>.</li>
                  <li><b>Settings → Channels → Microsoft Teams</b>, accept the terms, choose <b>Microsoft Teams Commercial</b>, <b>Apply</b>. The channel should show <b>Healthy</b>.</li>
                </ol>
              </SubStep>

              <SubStep title="4. Enter the credentials in Frappe">
                <ol>
                  <li>In <Desk to="/app/teams-settings">Teams Settings → Teams Bot</Desk>, tick <b>Enable Teams Bot</b>, enter <b>App ID</b>, <b>Tenant ID</b>, <b>Client Secret</b> (type it here; never send it by chat or email), <b>Secret Expiry Date</b> and <b>Bot Name</b>. Save.</li>
                  <li>Check that Microsoft accepts them (gets a token, sends nothing):</li>
                </ol>
                <button className="btn" onClick={checkBot} disabled={checkingBot || !s?.bot_started}>
                  <PlugZap size={14} className={checkingBot ? 'spin' : ''} /> Check bot connection
                </button>
                <p className="text-[13px]"><b>AADSTS7000215</b>: wrong secret, paste the <i>Value</i>. <b>AADSTS700016</b>: App ID not found in that tenant.</p>
              </SubStep>

              <SubStep title="5. Upload the Teams app">
                <p>Download the package <b>after</b> the Site URL is final; it lists this site's domain.</p>
                <a className="btn" href="/api/method/notification_engine.teams.api.download_app_package"><Download size={14} /> Download Teams app package</a>
                <p>Or from the terminal: <span className="kbd">bench --site {site} teams-notify build-manifest</span>. Then either:</p>
                <ul>
                  <li><b>Organisation-wide (Teams admin)</b>: <b>Teams admin center → Teams apps → Manage apps → Upload new app</b>. Allow it in a permission policy and, to install it for everyone, add it to an app setup policy.</li>
                  <li><b>Just you, for testing</b>: Teams → <b>Apps → Manage your apps → Upload an app → Upload a custom app</b> (needs custom app upload allowed).</li>
                </ul>
              </SubStep>

              <SubStep title="6. Link people and chats">
                <ol>
                  <li>Each person opens <b>{s?.bot_name || 'the app'}</b> in Teams (or it is pre-installed by policy). A <Link to="/users">Teams User Map</Link> row is created and matched to the Frappe user with the same email. Buttons act as that Frappe user, so the emails must match, or set <b>Frappe User</b> by hand.</li>
                  <li>To post into a group chat or channel, add the app to it (chat header → <b>Apps / +</b>). A <b>Bot Conversation</b> destination appears <b>turned off</b>; turn it on in <Link to="/destinations">Destinations</Link> and send a test.</li>
                  <li>Personal messages use the <b>Teams Bot (Personal)</b> destination, created automatically when the bot is enabled.</li>
                </ol>
              </SubStep>
            </Step>
          )}

          <Step id="rule" n={5} title="Create your first rule" checks={[['A rule is enabled', c('rule')]]}>
            <p>A Notification Rule says <i>when</i> to send (DocType + event + optional condition), <i>who</i> gets it (users, role, document field, designation, workflow approver…) and <i>how</i>: Email, System notification, SMS and Microsoft Teams, all from the same rule.</p>
            <ol>
              <li>Open <Desk to={deskUrl('Notification Rule') + '/new'}>New Notification Rule</Desk> and tick <b>Microsoft Teams</b> under Channels. Example for purchase approvals:
                <div className="overflow-x-auto my-2">
                  <table className="tbl text-[13px] border border-line">
                    <tbody>
                      <tr><td className="font-medium">Document Type / Event</td><td>Purchase Order · Value Change on <span className="kbd">workflow_state</span></td></tr>
                      <tr><td className="font-medium">Condition</td><td><span className="kbd">doc.workflow_state == "Approved"</span></td></tr>
                      <tr><td className="font-medium">Subject / Teams Title</td><td><span className="kbd">{'✅ PO Approved: {{ doc.name }}'}</span></td></tr>
                      <tr><td className="font-medium">Fields to Show</td><td>supplier, grand_total, schedule_date</td></tr>
                      <tr><td className="font-medium">Teams Chats / Channels</td><td>your chat destination (and/or a Personal Destination to message each recipient)</td></tr>
                    </tbody>
                  </table>
                </div>
              </li>
              <li>Only the fields you list leave Frappe. Title and body are Jinja templates with <span className="kbd">doc</span>; left empty, Teams uses the email Subject and Message.</li>
              <li>With the bot, add <b>Buttons</b> (workflow actions such as Approve / Reject, or Set Value) to act on the document from Teams.</li>
              <li>Busy rules: use <b>Cooldown</b> or an hourly / daily <b>Digest</b> instead of one card per event.</li>
              <li>Save, then <b>Test</b> it on <Link to="/rules">Rules</Link>. It renders against the latest document and sends with a [TEST] prefix.</li>
            </ol>
          </Step>

          <Step id="verify" n={6} title="Check it end to end" checks={[['Message delivered', c('delivered')]]}>
            <ol>
              <li>Create or change a real document so the rule's event and condition are met.</li>
              <li>Within a few seconds the card arrives in Teams. Its <b>Open in Frappe</b> button opens the document.</li>
              <li>The <Link to="/messages">Message Log</Link> shows it as <b>Sent</b>. Failures show the HTTP status and error, and can be resent after a fix.</li>
            </ol>
          </Step>

          <Step id="production" title="Production checklist">
            <ul>
              <li>Scheduler on and a worker for the Teams queue (step 2) supervised, so it restarts after reboots.</li>
              <li>Webhooks and the Azure Bot owned by a <b>service account</b> or with a co-owner, not one person.</li>
              <li><b>Secret Expiry Date</b> set: Teams Admins are warned 30 days before the bot's client secret expires. Renew it in Entra ID and paste the new value.{s?.secret_days_left != null && <> Now: <Pill tone={s.secret_days_left > 30 ? 'good' : 'warn'}>{s.secret_days_left} days left</Pill></>}</li>
              <li><b>Teams Admin</b> role given to the people who answer failure alerts.</li>
              <li>Data Import is silent by default; tick <b>Send During Import</b> on a rule only if you really want a card per imported row.</li>
            </ul>
          </Step>

          <Step id="troubleshooting" title="Troubleshooting">
            <div className="overflow-x-auto">
              <table className="tbl text-[13px] border border-line">
                <thead><tr><th>Symptom</th><th>What to check</th></tr></thead>
                <tbody>
                  {[
                    ['Nothing happens on save', 'Teams Notify enabled? Rule enabled? Condition true? Does the rule\'s Test work?'],
                    ['Messages stay Queued', 'Background workers and scheduler running (step 2)? sudo supervisorctl status'],
                    ['Throttled for a long time', 'Normal under load; webhooks accept only a few posts per second. Use a Digest for busy rules.'],
                    ['Sent, but no card in Teams', 'The workflow accepted it: check the flow\'s run history in Power Automate.'],
                    ['Webhook fails with 401 / 404', 'The workflow was deleted, turned off, or its owner left. Create a new one and update the destination.'],
                    ['Bot never replies, no Teams User Map rows', 'Messaging endpoint public HTTPS and identical to the one above? Microsoft Teams channel Healthy on the Azure Bot?'],
                    ['"Teams app not installed for this user"', 'Install the app for that person (setup policy or they open it once).'],
                    ['"Your Teams account isn\'t linked to ERP"', 'The Teams User Map row has no Frappe User: set it.'],
                    ['Check bot connection: AADSTS7000215', 'Wrong or expired client secret: create a new one and paste its Value.'],
                    ['Pages look stale after an update', 'bench build --app notification_engine, restart, then reload with Ctrl+Shift+R.'],
                  ].map(([a, b]) => <tr key={a}><td className="font-medium align-top">{a}</td><td className="text-ink-2">{b}</td></tr>)}
                </tbody>
              </table>
            </div>
            <p>Server-side details are in <span className="kbd">logs/notification_engine.log</span> and Frappe's <Desk to="/app/error-log">Error Log</Desk>.</p>
          </Step>

          <Step id="dashboard" title="Building this dashboard (developers)">
            <p>The dashboard is a React app in <span className="kbd">apps/notification_engine/frontend</span>. <span className="kbd">bench build --app notification_engine</span> builds it into <span className="kbd">notification_engine/public/frontend</span> and it is served at <span className="kbd">/teams-notify</span>. To work on it with hot reload:</p>
            <CodeBlock>{`cd ~/frappe-bench/apps/notification_engine/frontend
yarn install
FRAPPE_TARGET=http://127.0.0.1:8000 FRAPPE_SITE=${site} yarn dev   # http://localhost:8082/teams-notify
yarn build`}</CodeBlock>
          </Step>
        </div>

        <nav className="hidden lg:block sticky top-6 text-[13px]" aria-label="On this page">
          <div className="font-semibold mb-2 text-ink-2">On this page</div>
          <ul className="list-none m-0 p-0 flex flex-col gap-1">
            {SECTIONS.filter((x) => !x.sub || x.id === method).map((x) => (
              <li key={x.id}>
                <a href={`#${x.id}`} className={`block py-0.5 text-ink-2 hover:text-accent-text no-underline ${x.sub ? 'pl-3' : ''}`}>{x.title}</a>
              </li>
            ))}
          </ul>
          <a href="/app/teams-settings" className="btn btn-sm mt-4"><ExternalLink size={13} /> Teams Settings</a>
        </nav>
      </div>
    </>
  )
}
