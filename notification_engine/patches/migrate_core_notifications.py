import frappe

# NOTE: field names on core "Notification" / "Notification Recipient" have
# shifted slightly across Frappe versions. Before running this patch on your
# instance, confirm the exact fieldnames with:
#   bench --site <site> console
#   >>> frappe.get_meta("Notification Recipient").get_fieldnames_with_value()
# and adjust the filter below (receiver_by_role) if needed.

# Maps core Notification's "event" values to this app's event labels.
CORE_EVENT_MAP = {
	"New": "After Insert",
	"Save": "On Update",
	"Submit": "On Submit",
	"Cancel": "On Cancel",
	"Days After": "Days After",
	"Days Before": "Days Before",
	"Value Change": "Value Change",
	"Method": None,  # not supported 1:1 - flagged for manual review below
}


def execute():
	"""Non-destructive migration: creates an equivalent (disabled-by-default)
	Notification Rule for every enabled core Notification that uses Role as
	its recipient type, so an admin can review, populate real recipients,
	and enable each one deliberately rather than everything going live at
	once. The original core Notification records are left untouched -
	disable them manually once you've verified the replacement.
	"""
	if not frappe.db.table_exists("Notification"):
		return

	core_notifications = frappe.get_all(
		"Notification",
		filters={"enabled": 1, "channel": ["!=", ""]},
		fields=["name", "document_type", "event", "condition", "subject", "message", "channel"],
	)

	created, skipped = 0, []

	for cn in core_notifications:
		mapped_event = CORE_EVENT_MAP.get(cn.event)
		if not mapped_event:
			skipped.append(cn.name)
			continue

		recipients = frappe.get_all(
			"Notification Recipient",
			filters={"parent": cn.name, "receiver_by_role": ["is", "set"]},
			pluck="receiver_by_role",
		)
		if not recipients:
			# not role-based (e.g. email field / document field already) -
			# nothing to fix, skip
			continue

		role = recipients[0]

		new_title = f"[Migrated] {cn.name}"
		if frappe.db.exists("Notification Rule", new_title):
			continue

		rule = frappe.get_doc(
			{
				"doctype": "Notification Rule",
				"title": new_title,
				"is_enabled": 0,  # deliberately OFF - admin must review and turn on
				"reference_doctype": cn.document_type,
				"event": mapped_event,
				"condition": cn.condition,
				"recipient_source": "Role \u2192 Expand To Users",
				"role": role,
				"send_system_notification": 1 if "System Notification" in (cn.channel or "") else 0,
				"send_email": 1 if "Email" in (cn.channel or "") else 0,
				"subject": cn.subject or cn.name,
				"message": cn.message or "",
			}
		)
		rule.insert(ignore_permissions=True)
		rule.sync_from_role()
		created += 1

	frappe.db.commit()

	if created or skipped:
		frappe.log_error(
			title="Notification Engine migration summary",
			message=f"Created {created} draft Notification Rule(s) (disabled by default). "
			f"Skipped {len(skipped)} core Notification(s) using unsupported event 'Method': {skipped}",
		)
