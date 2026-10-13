> **Historical document.** This is the original specification of the standalone Teams Notify app.
> Teams Notify is now part of Notification Engine: the code is in `notification_engine/teams/`, and
> rules are Notification Engine's **Notification Rule** with **Microsoft Teams** ticked (there is no
> Teams Notification Rule or Teams Rule Recipient any more; recipients come from the rule's Recipient
> Source). See the main [README](../../README.md#microsoft-teams) for the current behaviour.

# Teams Notify: Technical Specification

> Implementation note (2026-10-06): the first build phase is **webhook delivery only**
> (M1, M2, M3 and a webhook-only M6). Bot messaging (M4) and Approve/Reject (M5)
> follow later. Rules are generic: any DocType, not only Purchase Order.

A standalone Frappe app that sends Microsoft Teams messages (group chats, channels and individual users) when events happen in Frappe / ERPNext, with optional Approve/Reject buttons that act back on ERPNext.

- **App name:** `teams_notify`
- **App title:** Teams Notify
- **Module:** Teams Notify
- **Target:** Frappe v15 and v16, with or without ERPNext. Self-hosted bench and Frappe Cloud.
- **Python:** 3.10+ (v15) / 3.11+ (v16)
- **License:** MIT

---

## 1. Goals

1. Admins create **no-code rules**: DocType + event + condition → message → destination(s) / recipient(s).
2. Deliver to **group chats, channels and individual users** in Microsoft Teams.
3. Support **two delivery methods** behind one interface:
   - **Workflows webhook** (Power Automate "When a Teams webhook request is received"). Simple, no Azure.
   - **Teams bot** (Azure Bot + Entra app, Bot Connector REST API). Branding, personal messages, **Approve/Reject buttons**.
4. **Reliable**: background queue, after-commit sending, rate limiting, retries, delivery log, resend.
5. **Safe**: secrets encrypted, field allow-lists, permission checks on every action from Teams.
6. **No changes to Frappe/ERPNext core.** Only public Frappe APIs and hooks.

### Out of scope
Reading Teams messages into Frappe, chat sync, meetings/calendar, AI chat bot, other channels (Slack, WhatsApp). Keep the delivery layer pluggable so these could be added later.

### Background facts (verify against current Microsoft docs before implementing)
- Office 365 Connectors / classic Incoming Webhooks are **retired** (disabled May 2026). Do **not** use them.
- Workflows webhooks: about **4 requests/second** per webhook before throttling; **28 KB** max message size.
- Microsoft Graph `chatMessage` POST supports app-only permission **only for migration**. Do **not** use Graph to post messages.
- The Python Bot Framework SDK (`botbuilder-*`) is **archived**. Use the **Bot Connector REST API directly** (preferred, keeps the app self-contained) or the Microsoft 365 Agents SDK.
- Bot rate limit: about **50 requests/second per app per tenant**, plus per-conversation limits. Honour `Retry-After`.

---

## 2. Architecture

```
Frappe document event / scheduler
        │
        ▼
Rule engine (cached rules → condition → recipients → render card)
        │   enqueue_after_commit=True, queue="teams", dedupe job_id
        ▼
Delivery job (worker)
        │  rate limit per destination (Redis token bucket)
        │  retry with backoff on 429 / 5xx
        ├──► WebhookSender ──► Workflows URL ──► Teams chat / channel / Flow-bot personal chat
        └──► BotSender ──► Bot Connector REST ──► Teams chat / channel / personal chat
        │
        ▼
Teams Message Log (status, attempts, payload, activity_id)

Teams ──► POST /api/method/teams_notify.bot.endpoint.receive
          (JWT validated) → install events, card actions (Approve/Reject)
```

### Package layout

```
teams_notify/
├── hooks.py
├── commands.py                 # bench commands (build manifest, test send)
├── api.py                      # public python API + whitelisted UI methods
├── tasks.py                    # scheduler jobs
├── engine/
│   ├── rules.py                # handle_doc_event, rule cache, matching
│   ├── conditions.py           # safe_eval of conditions
│   └── recipients.py           # resolve owner/field/role/assigned/user → users
├── cards/
│   ├── builder.py              # build Adaptive Card from rule + doc
│   └── default_card.json       # base template (Adaptive Card 1.4)
├── delivery/
│   ├── base.py                 # Sender interface + SendResult
│   ├── webhook.py              # WebhookSender
│   ├── bot.py                  # BotSender
│   ├── queue.py                # enqueue_message, deliver (RQ job)
│   ├── ratelimit.py            # Redis token bucket
│   └── digest.py               # buffer + flush
├── bot/
│   ├── auth.py                 # validate incoming JWT; get outgoing token
│   ├── connector.py            # Bot Connector REST client
│   ├── endpoint.py             # whitelisted receive()
│   └── handlers.py             # installationUpdate, conversationUpdate, invoke (actions)
├── teams_manifest/
│   ├── manifest.template.json
│   ├── color.png               # 192x192
│   └── outline.png             # 32x32 transparent
├── teams_notify/doctype/...    # DocTypes (section 3)
├── public/js/                  # form buttons (Test send, Resend)
└── tests/
```

---

## 3. DocTypes

All in module **Teams Notify**. Roles: create **Teams Admin** (full access to config). System Manager also has full access. Normal users: read their own logs only if needed (optional).

### 3.1 Teams Settings (Single)
| Field | Type | Notes |
|---|---|---|
| enabled | Check | Global kill switch |
| site_url | Data | Optional override for "Open in Frappe" links; default `frappe.utils.get_url()` |
| default_rate_per_second | Float | Default 1.0 |
| default_burst | Int | Default 4 |
| max_retries | Int | Default 5 |
| log_retention_days | Int | Default 30 |
| **Bot section** | | |
| bot_enabled | Check | |
| bot_app_id | Data | Entra App (client) ID |
| bot_tenant_id | Data | Tenant ID |
| bot_client_secret | Password | Encrypted |
| bot_secret_expiry | Date | Warn admins 30 days before |
| bot_name | Data | For manifest |
| graph_enabled | Check | Optional: use Graph for user lookup / app install |
| messaging_endpoint | Data (read-only) | Shows `{site_url}/api/method/teams_notify.bot.endpoint.receive` |

### 3.2 Teams Destination
| Field | Type | Notes |
|---|---|---|
| destination_name | Data, unique, autoname | e.g. "OCTO Team chat" |
| enabled | Check | |
| destination_type | Select | `Webhook`, `Webhook (Personal via Flow bot)`, `Bot Conversation` |
| webhook_url | Password | For webhook types |
| conversation_type | Select | `groupChat`, `channel`, `personal` (bot) |
| conversation_id | Data | Bot |
| service_url | Data | Bot |
| team_id / channel_id | Data | Bot, channel only |
| rate_per_second / burst | Float / Int | Optional overrides |
| consecutive_failures | Int, read-only | |
| last_success / last_error_at | Datetime, read-only | |
| last_error | Small Text, read-only | |

Bot conversations are **auto-created (disabled)** when the bot is added to a chat/team; admin enables them.

### 3.3 Teams Notification Rule
| Field | Type | Notes |
|---|---|---|
| rule_name | Data, unique | |
| enabled | Check | |
| document_type | Link DocType | |
| event | Select | `New`, `Save`, `Submit`, `Cancel`, `Delete`, `Value Change`, `Days Before`, `Days After`, `Method` |
| value_changed | Data (fieldname) | For Value Change |
| date_field / days | Data / Int | For Days Before/After |
| method | Data | For Method (doc_events method name) |
| condition | Code (Python expr) | Evaluated with `doc`; e.g. `doc.workflow_state == "Approved"` |
| title_template | Data (Jinja) | e.g. `✅ PO Approved: {{ doc.name }}` |
| body_template | Code (Jinja) | Optional markdown text |
| fields | Table → Teams Rule Field | Allow-list of fields shown as facts |
| include_open_button | Check | Default 1 |
| card_template | Code (Jinja → JSON) | Optional full Adaptive Card override |
| actions | Select | `None`, `Workflow Approve/Reject` |
| approve_action / reject_action | Data | ERPNext Workflow action names, e.g. `Approve`, `Reject` |
| destinations | Table → Teams Rule Destination | Group/channel destinations |
| recipients | Table → Teams Rule Recipient | Personal recipients |
| personal_delivery | Select | `Bot`, `Flow bot webhook` |
| personal_webhook | Link Teams Destination | For Flow-bot delivery |
| cooldown_minutes | Int | Skip repeat for same doc within window |
| digest | Select | `None`, `Hourly`, `Daily` |
| send_during_import | Check | Default 0 |

Child tables:
- **Teams Rule Field**: `fieldname`, `label` (optional).
- **Teams Rule Destination**: `destination` (Link Teams Destination).
- **Teams Rule Recipient**: `recipient_type` (`Owner`, `Document Field`, `Role`, `Assigned To`, `User`), `value` (fieldname / role / user).

Validation: condition compiles; templates render against a sample doc; fieldnames exist; actions only allowed if the DocType has an active Workflow; at least one destination or recipient.

### 3.4 Teams Message Log
| Field | Type |
|---|---|
| rule | Link |
| reference_doctype / reference_name | Link / Dynamic Link |
| destination | Link |
| recipient_user / recipient_email | Link User / Data |
| status | Select: `Queued`, `Sent`, `Failed`, `Throttled`, `Skipped` |
| attempts | Int |
| http_status | Int |
| error | Small Text |
| payload | Code (JSON) |
| dedupe_key | Data, unique index |
| activity_id / conversation_id | Data (bot; used to update cards) |
| sent_at | Datetime |

Button: **Resend**. Index on (`status`, `creation`).

### 3.5 Teams User Map
| Field | Type |
|---|---|
| user | Link User, unique |
| teams_email | Data |
| aad_object_id | Data |
| teams_user_id | Data (`29:...`) |
| conversation_id / service_url | Data (personal chat with bot) |
| installed | Check |
| last_seen | Datetime |

Auto-filled on bot install events (match by email / UPN). Admin can edit.

### 3.6 Teams Digest Buffer
`rule`, `destination`, `recipient_user`, `reference_doctype`, `reference_name`, `summary` (JSON), `period_key`.

---

## 4. Hooks

```python
_h = "teams_notify.engine.rules.handle_doc_event"
doc_events = {
    "*": {
        "after_insert": _h,
        "on_update": _h,
        "on_submit": _h,
        "on_cancel": _h,
        "on_trash": _h,
        "on_update_after_submit": _h,
    }
}
scheduler_events = {
    "hourly": ["teams_notify.delivery.digest.flush_hourly"],
    "daily": [
        "teams_notify.tasks.run_date_rules",
        "teams_notify.delivery.digest.flush_daily",
        "teams_notify.tasks.purge_old_logs",
        "teams_notify.tasks.warn_secret_expiry",
    ],
}
fixtures = [{"dt": "Role", "filters": [["name", "=", "Teams Admin"]]}]
```

Also add the `teams` queue to worker docs (`bench worker --queue teams`); fall back to `default` if the `teams` queue is not configured (make queue name a setting).

---

## 5. Rule engine

`handle_doc_event(doc, method)`:
1. Return immediately if settings disabled, or `frappe.flags.in_import / in_patch / in_install / in_migrate` (unless the rule has `send_during_import`).
2. Load rules for `doc.doctype` from `frappe.cache` (key `teams_notify:rules:{doctype}`). Clear cache on Rule `on_update` / `on_trash`. When no rules exist, this must cost microseconds.
3. Map `method` → event (`after_insert`→New, `on_update`→Save/Value Change, `on_submit`→Submit, `on_cancel`→Cancel, `on_trash`→Delete).
4. **Value Change**: use `doc.has_value_changed(fieldname)`.
5. Evaluate `condition` with `frappe.safe_eval(condition, None, {"doc": doc})`. Errors → Error Log, skip rule.
6. Cooldown check via cache key per (rule, doc).
7. Resolve recipients (owner, field value, users with role, `frappe.desk.form.assign_to.get` / `_assign`, fixed user). Deduplicate. Skip disabled users.
8. For each destination and recipient: build the card (section 6), then `enqueue_message(...)` with `enqueue_after_commit=True` and a **dedupe key** = `sha1(rule|doctype|name|event|doc.modified|target)`. If the rule is digest-mode, write to the Digest Buffer instead.

`run_date_rules()`: for Days Before/After rules, query docs whose `date_field` = today ± days, run steps 5–8.

Public API (`teams_notify.api`):
```python
send_to_teams(destination: str, card: dict | None = None, text: str | None = None,
              recipient_user: str | None = None, reference_doctype=None, reference_name=None)
```

---

## 6. Cards

- Adaptive Card **version 1.4** (widest compatibility for Workflows and bots).
- Default layout: title (bold, size Medium, colour by status: Good/Warning/Attention), optional body text, `FactSet` of allow-listed fields (use `doc.get_formatted(fieldname)` and field labels), action `Action.OpenUrl` → `{site_url}/app/{doctype-slug}/{name}`.
- If `actions == Workflow Approve/Reject` **and** delivery is via Bot: add `Action.Execute` buttons:
  ```json
  {"type": "Action.Execute", "title": "Approve", "verb": "teams_notify.workflow",
   "data": {"doctype": "Purchase Order", "name": "PUR-ORD-2026-00142", "action": "Approve", "log": "<log name>"}}
  ```
  For webhook delivery, omit these buttons (not supported reliably).
- Translate labels with `frappe._()`.
- Enforce **28 KB** max: if JSON is larger, truncate facts and add "Open in Frappe for full details".
- Never include fields that are not in the allow-list.

**Webhook payload envelope** (Workflows):
```json
{
  "type": "message",
  "attachments": [{
    "contentType": "application/vnd.microsoft.card.adaptive",
    "contentUrl": null,
    "content": { "...adaptive card..." }
  }],
  "recipient": "raj@octotech.com"
}
```
`recipient` is only sent for `Webhook (Personal via Flow bot)` destinations. The admin's Power Automate flow reads it (see Appendix B).

---

## 7. Delivery

### Interface
```python
class Sender(Protocol):
    def send(self, message: OutboundMessage) -> SendResult: ...
    def update(self, message: OutboundMessage, activity_id: str) -> SendResult: ...  # bot only
```
`SendResult`: `ok`, `http_status`, `retry_after`, `activity_id`, `conversation_id`, `error`.

### Job `delivery.queue.deliver(log_name)`
1. Load log + destination. Skip if destination disabled (status Skipped).
2. Take a token from the **Redis token bucket** keyed `teams_notify:rl:{site}:{destination}` (rate/burst from destination or settings). If none, re-enqueue with a 1–2 s delay (`frappe.enqueue(..., enqueue_after_commit=False)` plus scheduling via `at_front=False`, or RQ `enqueue_in` if available). Do not block the worker.
3. Call the sender. On success: status Sent, store activity/conversation ids, reset destination failure counters.
4. On 429/5xx/timeouts: attempts += 1, backoff `[5s, 30s, 2m, 10m, 1h]` (respect `Retry-After`), until `max_retries`, then Failed.
5. On 4xx (non-429): Failed immediately with error text.
6. After 5 consecutive failures on a destination, notify Teams Admin users (Frappe System Notification + email).

HTTP: `requests` with timeout 10 s. Never log webhook URLs or secrets.

### WebhookSender
`POST webhook_url` with the envelope JSON. Treat `200`/`202` as success.

### BotSender (Bot Connector REST)
- **Outgoing token**: `POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token`, `grant_type=client_credentials`, `client_id`, `client_secret`, `scope=https://api.botframework.com/.default`. Cache until 5 minutes before expiry (in `frappe.cache`).
- **Send to existing conversation**: `POST {service_url}/v3/conversations/{conversation_id}/activities` with `{"type":"message","attachments":[card attachment]}`. Store returned `id` as `activity_id`.
- **Update card**: `PUT {service_url}/v3/conversations/{conversation_id}/activities/{activity_id}`.
- **Personal chat with a user who has the app installed but no stored conversation**: `POST {service_url}/v3/conversations` with `bot` (`28:{app_id}`), `members` (the user's Teams id or AAD object id), `channelData.tenant.id`, `isGroup: false`. Store the returned conversation id in Teams User Map. Use the stored `service_url` (default `https://smba.trafficmanager.net/teams/` only as a fallback; verify the current value in Microsoft docs).
- If a user has no installation: log Failed with a clear "Teams app not installed for this user" error. If `graph_enabled`, optionally install via Graph `POST /users/{id}/teamwork/installedApps` (requires `TeamsAppInstallation.ReadWriteForUser.All`), then retry.

### Digest
Buffer rows grouped by (rule, destination/recipient); flush builds one card listing up to 20 items plus "and N more", then deletes rows.

---

## 8. Bot endpoint

`@frappe.whitelist(allow_guest=True, methods=["POST"])` `teams_notify.bot.endpoint.receive()`:

1. Return 403 unless `bot_enabled`.
2. **Validate the `Authorization: Bearer` JWT** from Bot Connector:
   - OpenID metadata: `https://login.botframework.com/v1/.well-known/openidconfiguration`, get `jwks_uri`, cache keys (24 h).
   - Verify signature (RS256), `aud == bot_app_id`, `iss == https://api.botframework.com`, `exp`/`nbf` with 5 min clock skew, and that the `serviceUrl` claim matches the activity's `serviceUrl`.
   - Use `PyJWT` (`jwt.PyJWKClient`). Reject on any failure (401).
   - Verify the exact issuer/metadata URLs for single-tenant bots in current Microsoft docs.
3. Parse the activity from `frappe.request.get_data()`.
4. Check `channelData.tenant.id == bot_tenant_id`; otherwise ignore.
5. Dispatch:
   - `installationUpdate` / `conversationUpdate` (bot added): create/update a **Teams Destination** (disabled) for group chats/channels; for personal scope, upsert **Teams User Map** (`aadObjectId`, `id`, conversation id, service url). Fetch member email via `GET {service_url}/v3/conversations/{id}/members/{userId}` to match the Frappe user.
   - `invoke` with `name == "adaptiveCard/action"` and `verb == "teams_notify.workflow"`: run section 9.
   - `message`: reply with short help text ("I send ERP notifications. Open ERPNext: link").
6. Respond within about 5 seconds. Heavy work → enqueue.

---

## 9. Approve / Reject from Teams

1. Identify the clicker: `activity.from.aadObjectId` → Teams User Map → Frappe user. Unknown → return an error card "Your Teams account isn't linked to ERP".
2. Load doc. If its workflow state no longer allows that action (already approved/rejected) → return a card "Already {state} by {user}".
3. `frappe.set_user(user)`; check `frappe.has_permission(doctype, "write", doc)` and that the action is in `frappe.model.workflow.get_transitions(doc)`. Then `frappe.model.workflow.apply_workflow(doc, action)`. Commit. Always restore the user in `finally`.
4. Add a comment on the doc: "Approved from Microsoft Teams by {user}".
5. Respond to the invoke with HTTP 200 and the **refreshed card** (`statusCode: 200`, `type: application/vnd.microsoft.card.adaptive`) showing "✅ Approved by {full name} at {time}" without buttons.
6. Enqueue updates for other copies of the same card (other logs with the same reference) using `update()`.
7. Use a lock (`frappe.cache` key per doc) to block double-clicks.

---

## 10. Teams app manifest

- Template in `teams_manifest/manifest.template.json` (use the current stable manifest schema version; verify in Microsoft docs).
- `bots[0].botId = bot_app_id`, `scopes = ["personal", "team", "groupChat"]`, `supportsFiles: false`, `isNotificationOnly: false`.
- `validDomains`: the Frappe site domain.
- `webApplicationInfo.id = bot_app_id` (needed for some admin/install flows).
- Command `bench --site <site> teams-notify build-manifest` writes `teams_notify_app.zip` (manifest + icons) into the site's private files and prints the path. IT uploads this zip in Teams Admin Center.

---

## 11. UI

- Rule form: **Send test** button. Renders against the latest doc of that DocType (or a selected doc) and sends to all destinations with a "[TEST]" title prefix.
- Destination form: **Send test message**, shows last success/error.
- Message Log list: filters by status; **Resend** button (bulk too).
- Settings: shows messaging endpoint (copy), secret expiry warning banner, **Check bot connection** (gets a token).
- Workspace "Teams Notify" with shortcuts and a number card: Sent today / Failed today.

---

## 12. Security

- Webhook URLs and client secret in **Password** fields only; never returned to the browser in plain text, never logged.
- Config DocTypes permitted to **System Manager** and **Teams Admin** only.
- Conditions use `frappe.safe_eval`; templates rendered with `frappe.render_template` (sandboxed Jinja).
- Bot endpoint: JWT validation is mandatory; tenant check; no action without a Frappe permission check.
- Only allow-listed fields leave Frappe.

---

## 13. Testing

- `FrappeTestCase` unit tests with `unittest.mock` for HTTP (no real network calls in CI).
- Cover: rule matching per event, Value Change, condition errors, recipients resolution, cooldown, dedupe, card size truncation, webhook success/429/500/400 paths, token bucket, retry schedule, digest flush, JWT validation (valid, bad aud, bad iss, expired, wrong tenant), approve flow (allowed, not permitted, already approved, unknown user).
- Integration test (manual, documented): PO approval → OCTO Team chat via webhook; Approve from Teams via bot.
- GitHub Actions CI: install on Frappe v15 and v16, run `bench run-tests --app teams_notify`.

---

## 14. Milestones and acceptance criteria

**M1: Scaffold.** App, module, role, all DocTypes, settings, hooks wired, installs and uninstalls cleanly.
✅ `bench install-app teams_notify` works on v15 and v16.

**M2: Webhook MVP.** Rule engine, card builder, WebhookSender, queue, log, test buttons.
✅ Approving a Purchase Order posts a card to a Workflows webhook (OCTO Team chat) within 10 s; failures are logged and resendable; saving a doc with no rules adds < 5 ms.

**M3: Reliability.** Token bucket, retries/backoff, digest, import suppression, cooldown, purge, failure alerts, Flow-bot personal webhook.
✅ 200 rapid events to one destination are delivered without a 429 storm; digest sends one card per period.

**M4: Bot messaging.** JWT-validated endpoint, install handling, auto-created destinations, User Map, BotSender (group chat, channel, personal), manifest builder.
✅ Bot added to a chat creates a destination; personal message reaches a mapped user.

**M5: Actions.** Approve/Reject with permission checks, card refresh, double-click lock, doc comment.
✅ Approver clicks Approve in Teams → ERPNext PO is Approved, card updates, unauthorised users are refused.

**M6: Release.** README (install, IT setup, Power Automate steps), CHANGELOG, CI green, sample rules fixture (disabled).

---

## 15. Example rule: PO approval

| Field | Value |
|---|---|
| Rule name | PO Approved → OCTO Team |
| Document type | Purchase Order |
| Event | Value Change |
| Value changed | workflow_state |
| Condition | `doc.workflow_state == "Approved"` |
| Title | `✅ PO Approved: {{ doc.name }}` |
| Fields | supplier, grand_total, schedule_date, modified_by |
| Destinations | OCTO Team chat |
| Recipients | Owner (personal message) |

Second rule, **PO Pending Approval → Approver** (bot, actions = Workflow Approve/Reject, recipients = Role "Purchase Manager", condition `doc.workflow_state == "Pending Approval"`).

If the site doesn't use an ERPNext Workflow on Purchase Order, use Event = Submit instead.

---

## Appendix A: IT setup checklist (examples are sample values)

1. **Service account**: `erp-notify@octotech.com`, Member (not Guest), Microsoft 365 Business Basic (Teams + Power Automate).
2. **Memberships**: OCTO Team (group chat), Purchase → General, Accounts → Payments.
3. **Workflows allowed**, "Anyone" trigger permitted. Workflow `ERP – OCTO Team alerts` owned by the service account, co-owner `it.admin@octotech.com`. URL like `https://prod-12.centralindia.logic.azure.com:443/workflows/.../invoke?...&sig=...`
4. **Azure Bot + Entra app (single tenant)**: Bot `OCTO ERP Bot`, App ID `3f7a9c21-...`, Tenant ID `a1b2c3d4-...`, client secret (expiry `06-Oct-2027`).
5. **Teams channel enabled** on the bot; **messaging endpoint** `https://erp.octotech.com/api/method/teams_notify.bot.endpoint.receive` (public HTTPS).
6. **Upload Teams app zip** (from `build-manifest`), **pre-install for users** via an app setup policy, **add bot to OCTO Team chat**.
7. Optional Graph admin consent: `User.Read.All`, `TeamsAppInstallation.ReadWriteForUser.All`.

## Appendix B: Power Automate flow for personal messages (Flow bot)

1. Trigger: **When a Teams webhook request is received**, Who can trigger: **Anyone**.
2. Action: **Post card in a chat or channel**:
   - Post as: **Flow bot**
   - Post in: **Chat with Flow bot**
   - Recipient: expression `triggerBody()?['recipient']`
   - Adaptive Card: expression `triggerBody()?['attachments'][0]['content']`
3. Save, copy the URL into a Teams Destination of type `Webhook (Personal via Flow bot)`.
