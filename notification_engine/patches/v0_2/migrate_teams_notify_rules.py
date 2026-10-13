import frappe

# Teams Notify event -> Notification Rule event.
EVENT_MAP = {
	"New": "After Insert",
	"Save": "On Update",
	"Submit": "On Submit",
	"Cancel": "On Cancel",
	"Delete": "On Trash",
	"Value Change": "Value Change",
	"Days Before": "Days Before",
	"Days After": "Days After",
}
# Teams Notify "Method" event: the document method -> Notification Rule event.
METHOD_MAP = {
	"after_insert": "After Insert",
	"on_update": "On Update",
	"on_update_after_submit": "On Update",
	"on_submit": "On Submit",
	"on_cancel": "On Cancel",
	"on_trash": "On Trash",
}
OLD_RULE = "Teams Notification Rule"
OLD_DOCTYPES = (OLD_RULE, "Teams Rule Recipient")
# Child tables now used by Notification Rule: old parentfield -> new parentfield.
CHILD_TABLES = {
	"Teams Rule Destination": ("destinations", "teams_destinations"),
	"Teams Rule Field": ("fields", "teams_fields"),
	"Teams Rule Button": ("buttons", "teams_buttons"),
}
SAVEPOINT = "migrate_teams_notify_rule"
CHILD_SKIP = {"name", "parent", "parenttype", "parentfield", "idx", "owner", "creation", "modified", "modified_by", "docstatus"}


def execute():
	"""Take over the rules of the former standalone Teams Notify app.

	Every Teams Notification Rule becomes a Notification Rule with the same name and
	"Microsoft Teams" ticked, so Teams Message Logs, digests and buttons on cards already posted
	in Teams keep pointing at a rule. Rules whose recipients cannot be expressed exactly are
	created disabled, with a note, for an admin to finish. Then the old DocTypes are removed.

	Reads the old tables with SQL: the teams_notify code may no longer be on this bench.
	"""
	if not frappe.db.table_exists(OLD_RULE):
		return

	converted, needs_review = [], []
	for old in frappe.db.sql(f"select * from `tab{OLD_RULE}` order by creation", as_dict=True):
		if frappe.db.exists("Notification Rule", old.name):
			needs_review.append(f"{old.name} (a Notification Rule with this name already exists, not converted)")
			continue
		exact = convert(old)
		(converted if exact else needs_review).append(old.name)

	for doctype in CHILD_TABLES:
		frappe.db.delete(doctype, {"parenttype": OLD_RULE})
	for doctype in OLD_DOCTYPES:
		frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True, ignore_missing=True)
	# Kept if the site has its own (custom) DocTypes in that module.
	if frappe.db.exists("Module Def", "Teams Notify") and not frappe.db.exists("DocType", {"module": "Teams Notify"}):
		frappe.delete_doc("Module Def", "Teams Notify", force=True, ignore_permissions=True)

	from notification_engine.teams.install import setup

	setup()
	frappe.db.commit()
	# Deleting a standard DocType keeps its table. DDL commits, so it runs last.
	for doctype in OLD_DOCTYPES:
		frappe.db.sql_ddl(f"drop table if exists `tab{doctype}`")

	if converted or needs_review:
		frappe.log_error(
			title="Notification Engine: Teams Notify rules migrated",
			message=f"Converted: {converted}\nCreated disabled, review recipients: {needs_review}",
		)


def convert(old) -> bool:
	"""Create the Notification Rule for one Teams Notification Rule. True if nothing needs review."""
	recipients, exact, note = map_recipients(old)
	event = METHOD_MAP.get(old.method) if old.event == "Method" else EVENT_MAP.get(old.event)
	if not event:
		event, exact, note = "On Update", False, f"Event {old.event!r} has no equivalent; set the event."

	rule = frappe.get_doc(
		{
			"doctype": "Notification Rule",
			"title": old.rule_name or old.name,
			"is_enabled": 1 if (old.enabled and exact) else 0,
			"reference_doctype": old.document_type,
			"event": event,
			"value_changed_field": old.value_changed,
			"date_field": old.date_field,
			"days_offset": old.days,
			"condition": old.condition,
			"send_during_import": old.send_during_import,
			**recipients,
			"send_system_notification": 0,
			"send_email": 0,
			"send_sms": 0,
			"send_teams": 1,
			"subject": old.title_template or old.rule_name or old.name,
			"teams_title": old.title_template,
			"teams_title_color": old.title_color,
			"teams_body": old.body_template,
			"teams_include_open_button": old.include_open_button,
			"teams_card_template": old.card_template,
			"teams_all_workflow_actions": old.all_workflow_actions,
			"teams_personal_destination": old.personal_webhook,
			"teams_cooldown_minutes": old.cooldown_minutes,
			"teams_digest": old.digest or "None",
		}
	)
	for doctype, (old_field, new_field) in CHILD_TABLES.items():
		for row in frappe.get_all(
			doctype, filters={"parent": old.name, "parenttype": OLD_RULE, "parentfield": old_field}, fields=["*"], order_by="idx"
		):
			rule.append(new_field, {k: v for k, v in row.items() if k not in CHILD_SKIP})

	rule.flags.ignore_permissions = True
	frappe.db.savepoint(SAVEPOINT)
	try:
		rule.insert(set_name=old.name)
	except Exception as e:
		# Keep the rule rather than lose it: save it disabled and let an admin fix what failed.
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.clear_last_message()
		rule.is_enabled = 0
		rule.flags.ignore_validate = True
		rule.flags.ignore_mandatory = True
		rule.insert(set_name=old.name)
		exact, note = False, f"it did not pass validation: {frappe.utils.strip_html_tags(str(e))}"
	if note:
		rule.add_comment("Comment", f"Migrated from Teams Notify and left disabled: {note}")
	return exact


def map_recipients(old):
	"""Teams Notify recipient rows -> (Notification Rule recipient fields, exact?, note)."""
	rows = frappe.db.sql(
		"select recipient_type, value from `tabTeams Rule Recipient` where parent=%s order by idx", old.name, as_dict=True
	)
	if not rows:
		# Chats / channels only.
		return {"recipient_source": "Specific Users"}, True, None

	types = {r.recipient_type for r in rows}
	if types == {"User"}:
		users = [{"user": r.value, "is_enabled": 1} for r in rows if frappe.db.exists("User", r.value)]
		return {"recipient_source": "Specific Users", "recipients": users}, True, None

	if len(rows) == 1:
		row = rows[0]
		if row.recipient_type == "Owner":
			return {"recipient_source": "Document Field (User)", "document_field": "owner"}, True, None
		if row.recipient_type == "Assigned To":
			return {"recipient_source": "Assigned To"}, True, None
		if row.recipient_type == "Role" and frappe.db.exists("Role", row.value):
			users = frappe.get_all(
				"User",
				filters=[
					["name", "in", frappe.get_all("Has Role", {"role": row.value, "parenttype": "User"}, pluck="parent")],
					["enabled", "=", 1],
					["user_type", "=", "System User"],
				],
				pluck="name",
			)
			recipients = [{"user": u, "is_enabled": 1, "added_via": "Role Expansion"} for u in users]
			return {"recipient_source": "Role → Expand To Users", "role": row.value, "recipients": recipients}, True, None
		if row.recipient_type == "Document Field":
			df = frappe.get_meta(old.document_type).get_field(row.value)
			if row.value in ("owner", "modified_by") or (df and df.fieldtype == "Link" and df.options == "User"):
				return {"recipient_source": "Document Field (User)", "document_field": row.value}, True, None

	summary = ", ".join(f"{r.recipient_type}{': ' + r.value if r.value else ''}" for r in rows)
	users = [{"user": r.value, "is_enabled": 1} for r in rows if r.recipient_type == "User" and frappe.db.exists("User", r.value)]
	note = f"its recipients ({summary}) need one Recipient Source; only the User rows were copied."
	return {"recipient_source": "Specific Users", "recipients": users}, False, note
