import frappe
from frappe.utils import add_days, nowdate


def purge_old_logs():
	"""Daily: delete finished Teams Message Logs older than Teams Settings > Log Retention (Days)."""
	days = frappe.db.get_single_value("Teams Settings", "log_retention_days")
	if not days:
		return  # 0 keeps logs forever
	cutoff = add_days(nowdate(), -int(days))
	frappe.db.delete(
		"Teams Message Log",
		{"creation": ("<", cutoff), "status": ("not in", ("Queued", "Throttled"))},
	)
	# Digest rows should be flushed within a day; anything this old belongs to a deleted rule.
	frappe.db.delete("Teams Digest Buffer", {"creation": ("<", add_days(nowdate(), -7))})


def warn_secret_expiry():
	"""Daily: warn Teams Admins 30, 14, 7, 3, 1 and 0 days before the bot client secret expires."""
	from frappe.utils import date_diff, getdate

	from notification_engine.teams.delivery.queue import _users_with_role

	if not frappe.db.get_single_value("Teams Settings", "bot_enabled"):
		return
	expiry = frappe.db.get_single_value("Teams Settings", "bot_secret_expiry")
	if not expiry:
		return
	days = date_diff(getdate(expiry), getdate(nowdate()))
	if days not in (30, 14, 7, 3, 1, 0) and days >= 0:
		return
	if days < 0 and days % 7:
		return  # once expired, remind weekly

	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	subject = (
		frappe._("The Teams bot client secret expires in {0} day(s)").format(days)
		if days >= 0
		else frappe._("The Teams bot client secret expired {0} day(s) ago").format(-days)
	)
	users = _users_with_role("Teams Admin") or _users_with_role("System Manager")
	if users:
		enqueue_create_notification(
			users,
			{
				"type": "Alert",
				"document_type": "Teams Settings",
				"document_name": "Teams Settings",
				"subject": subject,
				"email_content": frappe._("Create a new secret in Entra ID and update Teams Settings."),
			},
		)
