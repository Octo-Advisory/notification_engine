# Notification Engine

A generic, user-level notification engine for Frappe / ERPNext.

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

## Installation

```bash
bench get-app notification_engine /path/to/this/folder
bench --site your-site install-app notification_engine
bench --site your-site migrate
```

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
4. Tick the channels you want: System Notification, Email, SMS.
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
8. Tick **Enabled** and save.

## Channels

| Channel | Requires |
|---|---|
| System Notification | nothing extra - uses Frappe's own Notification Log |
| Email | User must have an email address (standard) |
| SMS | `Notification Engine Settings` gateway config; mobile number resolved from `Employee.cell_number`, falling back to `Contact.mobile_no` |

## Auditing deliveries

Follows the same pattern Frappe's own core Notification relies on: rather
than storing a second copy of every email/notification body, **Notification
Engine Log** keeps a thin record (rule, channel, status, recipient) and
**links to Frappe's own native record** for the full detail:

- **Email** → links to the **Communication** record `frappe.sendmail()`
  already creates automatically - the exact same one visible in the
  reference document's Timeline, with full body, delivery status, and any
  tracked opens/replies.
- **System Notification** → links to the **Notification Log** record - the
  actual entry shown in the recipient's bell icon.
- **SMS** → Frappe has no native record for this, so Subject/Content are
  stored directly on our log for that channel only.

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

## Extending

- New channels: drop a `send(rule, doc, users, subject, message)` function
  into `notification_engine/channels/`, and call it from
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
