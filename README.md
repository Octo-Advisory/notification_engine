# Notification Engine

A generic, user-level notification engine for Frappe / ERPNext, with
**Email, System Notification, SMS and Microsoft Teams** in one app. One
**Notification Rule** decides *when* (DocType + event + condition), *who*
(specific users, role, document field, designation, department, assignee,
workflow approver) and sends on every channel you tick, all at once.

Solves the core problem with ERPNext's built-in workflow notifications:
they target a **Role**, so every user who happens to share that role gets
notified about every document, whether it's relevant to them or not. This
app resolves notifications down to **specific users**, with independent
enable/disable switches at three levels:

1. **Rule level** - `Notification Rule.is_enabled` turns the whole rule on/off.
2. **Recipient level** - each user in a rule's recipient table has their own
   `is_enabled` checkbox, so you can silence one person out of a group
   without removing them.
3. **Personal level** - `Notification User Preference` lets an individual
   user opt out of a rule for themselves (self-service, mirrors Frappe's own
   Notification Settings UX).

Microsoft Teams (formerly the separate Teams Notify app) is built in: cards
to group chats, channels and individual people through a Workflows webhook
or your own Teams bot, with **Approve / Reject** buttons, digests, a
reliable background queue and an admin dashboard at `/teams-notify`. See
[Microsoft Teams](#microsoft-teams).

Works on Frappe v15 (ERPNext optional: only the Designation, Department and
Workflow Roles recipient sources and SMS mobile numbers need it).

## Contents

- [Installation](#installation)
- [Setting up your first rule](#setting-up-your-first-rule)
- [Channels](#channels)
- [Microsoft Teams](#microsoft-teams)
- [Auditing deliveries](#auditing-deliveries)
- [Migrating from core ERPNext Notifications](#migrating-from-core-erpnext-notifications)
- [Moving from the Teams Notify app](#moving-from-the-teams-notify-app)
- [Extending](#extending)
- [Workflow Roles (Project + Department)](#workflow-roles-project--department)
- [Updating, troubleshooting and development](#updating)

## Installation

Requirements: Frappe v15 on a bench you can run commands on, and Node 18+
with yarn (`bench build` builds the Teams dashboard).

```bash
cd ~/frappe-bench
bench get-app https://github.com/Octo-Advisory/notification_engine.git
bench --site your-site install-app notification_engine
bench --site your-site migrate
bench build --app notification_engine
```

Then restart so web and background workers load the new code
(`sudo supervisorctl restart all` in production, or restart `bench start`).

Notifications are sent by background workers and the scheduler (Teams
retries and digests run every minute / hour / day, date-based rules daily):

```bash
bench --site your-site enable-scheduler
```

Installing also creates the **Teams Admin** role (give it to people who
manage Teams destinations; System Managers already have access) and an
internal, role-less bot user (`teams-bot@teams-notify.invalid`) used only for
validated requests from Microsoft Teams.

Already using the standalone **teams_notify** app on the site? Read
[Moving from the Teams Notify app](#moving-from-the-teams-notify-app) first.

## Setting up your first rule

1. Go to **Notification Rule** (new).
2. Pick the **Reference Document Type** (e.g. `Leave Application`) and
   **Event** (e.g. `On Update`, or `Value Change` if you only care when a
   specific field like `status` changes).
3. Choose a **Recipient Source**:
   - *Specific Users* - manually add rows to the Recipients table.
   - *Role → Expand To Users* - pick a Role, then click **Sync From Role**
     to populate the Recipients table with that role's current members.
     Re-running the sync later only **adds** new members; it never
     re-enables someone you've manually disabled.
   - *Document Field (User)* - point at a field on the document itself
     (e.g. `owner`, `leave_approver`) for fully dynamic, per-document
     targeting.
   - *Workflow Roles (Project + Department)* - for workflows where the
     right person depends on which Project/Department the document
     belongs to (see below).
   - *Assigned To* - the users the document is assigned to.
   - *Designation* / *Department* - every active Employee with that
     Designation / in that Department who is linked to a User. Needs ERPNext
     (Employee); on a site without it the rule cannot be saved with these
     sources.
4. Tick the channels you want: System Notification, Email, SMS and
   **Microsoft Teams** - one rule sends on all of them at once. A Teams
   rule may also post only to Teams chats / channels, with no individual
   recipients at all.
5. If Email is on, choose a **Delivery Mode**:
   - *Individual Emails* - one send per recipient (uses one provider credit per person; use only when credits aren't a concern or true 1:1 messaging is needed).
   - *Single Email (To)* - one send total, all recipients visible to each other in To.
   - *Single Email (BCC)* - one send total, recipients hidden from each other in Bcc (recommended default for saving credits while keeping privacy).
6. Optionally add **CC** / **BCC** rows. Each row can carry its own condition
   (e.g. `doc.grand_total > 100000`) so a recipient is only cc'd/bcc'd when
   that condition is true for the specific document - leave blank to always
   include that row.
7. Write **Subject** and **Message** (Jinja templates; the document is
   available as `doc`, e.g. `{{ doc.name }}`, `{{ doc.grand_total }}`).
   Teams uses them too unless you write a separate Teams Title / Body.
8. If Teams is on, fill the **Microsoft Teams** section (see below).
9. Tick **Enabled** and save.

Data Import, patches and migrate do not notify anyone, unless a rule has
**Send During Data Import** ticked.

## Channels

| Channel | Requires |
|---|---|
| System Notification | nothing extra - uses Frappe's own Notification Log |
| Email | User must have an email address (standard) |
| SMS | `Notification Engine Settings` gateway config; mobile number resolved from `Employee.cell_number`, falling back to `Contact.mobile_no` |
| Microsoft Teams | **Teams Settings → Enabled**, and at least one **Teams Destination** (a Workflows webhook or the Teams bot). See [Microsoft Teams](#microsoft-teams). |

## Microsoft Teams

### Turn it on

1. Open **Teams Settings** (`/app/teams-settings`) and tick **Enabled** - the
   global switch for every Teams message. The defaults are fine for most
   sites: rate per second / burst per destination (Workflows webhooks
   throttle at about 4 requests per second), retries on 429 / 5xx /
   timeouts (after 5 s, 30 s, 2 min, 10 min, 1 h), a failure alert to Teams
   Admins after N failures in a row, log retention, and **Site URL** if
   "Open in Frappe" links must use a public address.
2. Optional, for busy sites: a dedicated `teams` queue so Teams messages
   never wait behind long reports. Add to `sites/common_site_config.json`:
   `"workers": {"teams": {"timeout": 300}}`, then `bench setup supervisor`
   (production) or `worker_teams: bench worker --queue teams` in the
   `Procfile` (development). Until then messages use the `default` queue.
3. Sign in as System Manager or Teams Admin and open the dashboard at
   `https://your-site/teams-notify`: delivery stats, message log with
   **Resend**, the Teams rules with **Test**, destinations with **Send
   test**, linked Teams users, and a live **Install Guide** that ticks off
   each setup step against your site.

### Choose a delivery method

|  | Workflows webhook | Teams bot |
|---|---|---|
| Setup | About 10 minutes, inside Teams | Azure Bot + Entra app + Teams app upload |
| Public HTTPS URL for Frappe | Not needed | Required |
| Group chats and channels | Yes | Yes (add the bot to the chat) |
| Personal messages | Yes, through the Flow bot | Yes, from your own branded bot |
| Approve / Reject buttons | No | Yes, acting as the person who clicks |

**Webhook.** Office 365 Connectors are retired; use a **Workflows** webhook.
In the Teams chat or channel: **⋯ → Workflows → Send webhook alerts to a
chat** (or channel), **Add workflow**, copy the URL (treat it like a
password). In Frappe: **Teams Destination → New**, Type **Webhook**, paste
the URL, save, then **Send test**. For personal messages without a bot,
create a second flow (trigger *When a Teams webhook request is received*,
Who can trigger *Anyone*; action *Post card in a chat or channel* as **Flow
bot** in **Chat with Flow bot**, Recipient `triggerBody()?['recipient']`,
Adaptive Card `triggerBody()?['attachments'][0]['content']`) and add it as a
**Webhook (Personal via Flow bot)** destination.

**Teams bot.** Usually done by IT:

1. The site needs a public HTTPS address. The messaging endpoint is
   `https://your-site/api/method/notification_engine.teams.bot.endpoint.receive`
   (Teams Settings shows it with a copy button). Bots set up with the old
   Teams Notify endpoint (`.../teams_notify.bot.endpoint.receive`) keep
   working. For testing, a tunnel works: [docs/teams/BOT_TUNNEL_SETUP.md](docs/teams/BOT_TUNNEL_SETUP.md).
2. **Entra ID → App registrations → New registration** (Single tenant).
   Copy the Application (client) ID and Directory (tenant) ID, and create a
   client secret (copy its *Value*, note its expiry).
3. **Create a resource → Azure Bot**, Single Tenant, *Use existing app
   registration*. Paste the messaging endpoint under **Configuration**, and
   enable the **Microsoft Teams** channel (it should show *Healthy*).
4. **Teams Settings → Teams Bot**: tick **Enable Teams Bot**, enter App ID,
   Tenant ID, Client Secret, Secret Expiry Date and Bot Name, save, then
   **Check Bot Connection** (`AADSTS7000215` = wrong secret,
   `AADSTS700016` = App ID not in that tenant).
5. Download the Teams app package once the Site URL is final (**Teams
   Settings → Download Teams App Package**, or
   `bench --site your-site notification-engine build-teams-manifest`) and
   upload it in **Teams admin center → Teams apps → Manage apps**.
6. Each person opens the app once (or it is pre-installed by policy): a
   **Teams User Map** row links them to the Frappe user with the same email.
   Add the app to a group chat or channel to get a **Bot Conversation**
   destination (created turned off; turn it on and send a test). Personal
   messages use the **Teams Bot (Personal)** destination.

### Teams on a rule

Tick **Microsoft Teams** under Channels; the **Microsoft Teams** section
appears:

- **Teams Chats / Channels** - one message per chat or channel, whoever the
  recipients are.
- **Personal Destination** - a personal message to each resolved recipient
  (opt-outs apply), through a *Bot (Personal Chat)* or *Webhook (Personal via
  Flow bot)* destination.
- **Teams Title** / **Teams Body** - optional. Empty, the card uses the
  Subject and the Message (converted from HTML to Markdown, which is what
  Teams cards show). **Fields to Show** lists the only document fields that
  leave Frappe. **Card Template** replaces all of it with your own Adaptive
  Card JSON.
- **Buttons** (Teams bot only) - workflow actions such as Approve / Reject
  (or all of them), or *Set Value* buttons. Every click runs as the Frappe
  user linked to the person who clicked, with their permissions.
- **Cooldown** and an **Hourly / Daily Digest** for busy rules.
- **Send Teams Test** (form button, or **Test** on the dashboard) renders the
  card against the latest document and sends it with a `[TEST]` prefix.

Every Teams message gets a **Teams Message Log** (Queued → Sent / Failed /
Throttled, with the HTTP status, error and **Resend**) and a *Teams* row in
the rule's **Notification Engine Log**, linked to it.

Production checklist: scheduler and a worker for the Teams queue running;
webhooks and the Azure Bot owned by a service account; **Secret Expiry
Date** set (Teams Admins are warned 30 days before the bot secret expires);
the Teams Admin role given to whoever should get failure alerts. The full
manual test plan is in [docs/teams/TESTING.md](docs/teams/TESTING.md) and the
technical specification in [docs/teams/SPEC.md](docs/teams/SPEC.md).

## Auditing deliveries

Follows the same pattern Frappe's own core Notification relies on: rather
than storing a second copy of every email/notification body, **Notification
Engine Log** keeps a thin record (rule, channel, status, recipient) and
**links to Frappe's own native record** for the full detail:

- **Email** → links to the **Communication** record created for the email
  (the same way core Notification does it) - the one visible in the
  reference document's Timeline, with full body, delivery status, and any
  tracked opens/replies.
- **System Notification** → links to the **Notification Log** record - the
  actual entry shown in the recipient's bell icon.
- **SMS** → Frappe has no native record for this, so Subject/Content are
  stored directly on our log for that channel only.
- **Teams** → links to the **Teams Message Log**. Teams delivers in the
  background, so this row says *Queued*; the Teams Message Log has the final
  Sent / Failed status.

Every log row also always shows Status (Success / Failed / Skipped,
color-coded in the list view) and an Error Message when something went
wrong. If a send fails *before* Frappe creates its native record, the
Subject/Content fallback fields catch that content so nothing is lost.

Open any Notification Rule and check its **Delivery** connection count
(bottom of the form) or click **View Delivery Log** to filter straight to
its history.

## Migrating from core ERPNext Notifications

Run `bench --site your-site migrate` after installing - the
`migrate_core_notifications` patch scans existing role-based core
`Notification` records and creates an equivalent **disabled** Notification
Rule for each one, so you can review, populate real recipients, and enable
them deliberately rather than everything going live at once. It does not
touch or delete the original core records.

## Moving from the Teams Notify app

Notification Engine contains everything the standalone `teams_notify` app
did, with the same Teams DocTypes, so a site can switch without losing
destinations, settings, logs or rules:

```bash
bench --site your-site backup
bench --site your-site remove-from-installed-apps teams_notify   # keeps its tables and data
bench --site your-site migrate                                    # with this app installed
bench build --app notification_engine
```

Migrate refuses to run while `teams_notify` is still installed on the site.
The `migrate_teams_notify_rules` patch turns every **Teams Notification
Rule** into a **Notification Rule** with the same name and Microsoft Teams
ticked, so message logs, digests and buttons on cards already posted in
Teams keep working; then it removes the old rule DocTypes. Rules whose
recipients can't be expressed with one Recipient Source (mixed recipient
rows, or a document field holding plain email addresses) are created
**disabled** with a comment saying what to finish. Two differences to know:

- A *Role* recipient becomes *Role → Expand To Users*: a snapshot of the
  role's users at migration time (use **Sync From Role** to refresh),
  instead of the role's members at send time.
- Bots registered with the old messaging endpoint keep working; update it in
  the Azure Bot when convenient.

## Extending

- New channels from another app: register a function in that app's
  `hooks.py`, no change to this app needed:

  ```python
  notification_engine_channels = ["my_app.integrations.notify.send"]
  ```

  The dispatcher calls `send(rule, doc, users, subject, message)` for every
  rule it fires, after the built-in channels, with the users already
  resolved (opt-outs applied) and the subject/message already rendered. The
  function decides from the rule whether to send (e.g. a Custom Field
  checkbox it adds) and logs its own deliveries. A failure is written to the
  Error Log and never blocks other channels.
- New built-in channels: drop a `send(rule, doc, users, subject, message)`
  function into `notification_engine/channels/`, and call it from
  `engine/dispatcher.py`.
- New trigger types: extend the `event` Select options on `Notification
  Rule` and add handling in `engine/events.py`.

### Covering every workflow-enabled doctype, not just one

`Notify Only Current State's Approver` is doctype-agnostic by design - it
reads whatever the *current* Workflow says for whatever doctype the rule
targets, so the same mechanism works identically for Purchase Order,
Leave Application, or any custom doctype. The only real setup work is
creating one rule per doctype that has an active Workflow (each doctype
needs its own Project/Department fieldnames configured, since those
differ per doctype).

To avoid hand-creating a rule for every doctype one at a time, open the
**Notification Rule** list view and click **Generate Rules For All Active
Workflows**. This scans every DocType with an active Workflow and creates
a **draft, disabled** rule for each one that doesn't already have one
(Event = Value Change, Field To Watch = that workflow's actual state
field, Recipient Source = Workflow Roles (Project + Department), Notify
Only Current State's Approver = on). You still need to open each
generated rule and:
- Set **Project Field** / **Department Field** if that doctype has them
  (leave blank if it doesn't - not every doctype has project/department
  context, and that's fine).
- Adjust **Subject** / **Message**.
- Tick **Enabled** once you've verified it with **Preview Resolved Users**.

Nothing is auto-enabled - this only saves the typing, not the review.

## Workflow Roles (Project + Department)

Use this recipient source when the right person for a document depends on
*which* Project or Department it belongs to - e.g. a Purchase Order should
go to that specific project's team, or a Leave Application should go to
that employee's actual Department Head, not a role shared by every
department head in the company.

**This is fully automatic - there is no role to pick on the Notification
Rule itself.** Set:

1. **Project Field** - fieldname on the Reference Document Type holding
   the Project link (e.g. `project`). Everyone assigned in that project's
   own **Committee** table (`Project.custom_roles`, the "Project Role"
   child table) is automatically included, *provided* their committee
   role has a matching **Role Master** record with **Applicable** ticked.
   Role Master is where the actual binding lives: each row's `role` text
   (e.g. "Site In charge") is matched to a Role Master record of the same
   name, which carries the real Frappe Role in its **Internal Role Name**
   field. Committee rows whose role has no Role Master entry, or whose
   Role Master is marked not applicable, are skipped automatically - no
   need to enumerate every possible role anywhere.
2. **Department Field** - fieldname holding the Department link (e.g.
   `department`). That department's `custom_department_head_user_id` is
   automatically included.

Both are optional independently - set only Project Field if Department
doesn't apply, or vice versa, or set both to combine the two sources.

### Notifying only the current state's approver (recommended for approval workflows)

By default the whole applicable committee is notified for every event. If
what you actually want is "whoever needs to approve the document *right
now* gets emailed, and this should work automatically for every status"
(e.g. Cluster Head when pending CH approval, Site In charge when pending
site approval, without a separate rule per status) - tick **Notify Only
Current State's Approver**.

When this is on, the engine:
1. Finds the reference doctype's active Workflow and the document's
   current value in its workflow state field.
2. Looks up that state's `allow_edit` Role in `Workflow Document State` -
   this is the Role Frappe itself considers responsible for acting while
   the document sits in that state.
3. Resolves that Role through a **priority chain**, stopping at the first
   step that finds a valid person:
   - **Project Committee** - if a committee position is bound to that
     Role (via Role Master), and the person there is valid, use them.
   - **Department Head** - only counts if the department head *personally
     holds* that Role (checked via Frappe's own Role assignment) - this
     covers cases where the state's required approver genuinely is
     "whoever heads this department."
   - **Direct Role Holder** - anyone in the system directly assigned that
     Frappe Role, no project or department context needed at all. This is
     what covers company-wide singular roles like **CEO, MD, Purchase
     Head** - roles that were never going to appear in a Project
     Committee table to begin with, so they fall straight through to
     this step.

This means **one rule covers every workflow status, and every kind of
approver** - committee-based, department-based, or company-wide - without
a separate rule or condition per state or per role type. Pair this with
**Event = Value Change** and **Field To Watch** set to the workflow's
actual state fieldname (shown in the preview's state note) so the rule
fires exactly when the status changes.

Each Project Role row resolves its person directly from its own `user`
field if set, falling back to `Employee.user_id` via its
`project_employee` field otherwise.

**Every resolved user, from any step in the chain, is checked for an
active Employee record** before being included - someone who has left
the company (or has no Employee record at all) is automatically
excluded, and the reason is visible in the preview.

**Project Committee candidates get one more check:** the resolved user
must currently hold the actual Frappe Role their committee position
claims to be bound to (Role Master's Internal Role Name) - not just be
listed in the committee table. If someone's Role was changed or revoked
but their `Project Role` row was never updated to match, they're excluded
with that reason shown, and resolution falls through to the next step in
the chain (Department Head, then Direct Role Holder) rather than getting
emailed based on stale committee data.

**To test before going live:** set **Sample Reference Document** to an
existing document of that type, then click **Preview Resolved Users**.
If **Notify Only Current State's Approver** is on, the preview also shows
a note with the document's current state, which field it read that from,
and which Role that state requires - useful for confirming the workflow
lookup is finding the right thing. The table itself shows only users who
will actually be notified (excluded candidates aren't listed, just
summarized as a count) - Source (which committee role, or Department
Head), User, Employee, and the **Bound Role** from Role Master's Internal
Role Name - so you can visually confirm who's being notified and under
which actual Frappe Role they qualify.

### A note on workflow-triggered events

A workflow action button doesn't fire some special separate event - under
the hood it just sets the state field and calls the document's normal
`save()` / `submit()` / `cancel()`, which already fires the standard
document events this engine listens to (`On Update`, `On Submit`, `On
Cancel`). So for "notify when the workflow status changes", use **Event =
Value Change** with **Field To Watch** set to the workflow's state
fieldname (commonly `workflow_state`, but confirm via the Workflow
doctype's `workflow_state_field` - it can be a different name) - there is
no need for a distinct "workflow action" event type.

This assumes the standard ERPNext `Employee.user_id` and
`Employee.status` fields (active status = `"Active"`) - adjust
`engine/role_resolver.py`'s `_validate_active_employee()` if your
instance uses different status values.

If you also need a fixed global recipient regardless of project/department
(e.g. always notify the CEO), that's simplest as a **separate** Notification
Rule on the same doctype/event using "Role → Expand To Users" or "Specific
Users" - both rules fire independently for the same document.

## Updating

```bash
cd ~/frappe-bench
bench update --apps notification_engine   # or: cd apps/notification_engine && git pull
bench --site your-site migrate
bench build --app notification_engine
sudo supervisorctl restart all            # production
```

Reload the Teams dashboard with Ctrl+Shift+R if it still shows the old version.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Nothing happens on save | Rule enabled? Condition true? Recipients resolve to someone (or Teams chats set)? Was it a Data Import (see *Send During Data Import*)? For Teams: Teams Settings enabled, and does **Send Teams Test** work? |
| Teams messages stay **Queued** | Background workers and scheduler running? `sudo supervisorctl status` |
| **Throttled** for a long time | Normal under load: webhooks accept only a few posts per second. Use a Digest for busy rules. |
| Sent, but no card in Teams | Check the flow's run history in Power Automate. |
| Webhook fails with 401 / 404 | The workflow was deleted or turned off, or its owner left. Create a new one and update the destination. |
| Bot never replies, no Teams User Map rows | Messaging endpoint public over HTTPS and identical to the one in Teams Settings? Teams channel *Healthy* on the Azure Bot? |
| "Your Teams account isn't linked to ERP" | The Teams User Map row has no Frappe User: set it. |
| `/teams-notify` is blank or 404 | `bench build --app notification_engine` and restart. |

Server-side details are in `logs/notification_engine.log` and Frappe's
**Error Log** (`/app/error-log`).

## Development

```
notification_engine/
├── engine/          rule matching (events), recipients, conditions, dispatcher
├── channels/        System, Email, SMS
├── teams/           Microsoft Teams: rules.py (the Teams channel), cards/, delivery/
│                    (queue, webhook and bot senders, rate limit, digest), bot/ (endpoint,
│                    JWT validation, card actions), teams_manifest/, dashboard.py, doctype/
├── notification_engine/doctype/   Notification Rule, Log, User Preference, Settings
├── patches/         core Notification and Teams Notify migrations
└── www/             serves the Teams dashboard at /teams-notify
frontend/            Teams dashboard (React, Vite, Tailwind, frappe-react-sdk)
docs/teams/          Teams specification, manual test plan, bot tunnel setup
```

**Tests** (they mock every HTTP call; nothing is sent to Microsoft):

```bash
bench --site your-site set-config allow_tests true
bench --site your-site run-tests --app notification_engine
```

**Dashboard.** `bench build --app notification_engine` builds `frontend/`
into `notification_engine/public/frontend` (not committed). With hot reload:

```bash
cd ~/frappe-bench/apps/notification_engine/frontend
yarn install
FRAPPE_TARGET=http://127.0.0.1:8000 FRAPPE_SITE=your-site yarn dev   # http://localhost:8082/teams-notify
```

`yarn dev:demo` / `yarn build:demo` run the same dashboard on sample data
(`frontend/src/demo/`), with no Frappe site.
