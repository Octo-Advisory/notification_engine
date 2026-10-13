import frappe
from frappe.model.document import Document


class NotificationEngineLog(Document):
	pass


def create_log(notification_rule, channel, status, user=None, reference_doctype=None,
                reference_name=None, error_message=None, subject=None, content=None,
                recipient_address=None, communication=None, notification_log=None):
	"""Helper used by the dispatcher/channels to record a delivery attempt.

	Follows the same pattern Frappe's own core Notification uses: the actual
	content lives in Frappe's native records (Communication for email,
	Notification Log for system alerts) - we just keep a pointer to them
	plus rule/status metadata. `subject`/`content` are only the primary
	record for channels with no native equivalent (SMS); for Email/System
	they're a fallback populated only if linking to the native record fails.

	IMPORTANT - independent commit:
	This runs inside the same DB transaction as whatever document event
	triggered it (on_update, on_submit, etc). If anything ELSE later in that
	same request raises and the request rolls back, this insert would be
	rolled back too - but the email/SMS/system notification itself is an
	external side effect that can't be undone. So we commit this insert on
	its own, immediately, to guarantee the audit row survives even if the
	rest of the request later fails. This is deliberate and safe here: by
	the time any of our channels run, the reference document has already
	been fully saved earlier in the same hook chain.

	Intentionally fire-and-forget beyond that: logging failures must never
	break the actual notification flow, so this swallows its own exceptions
	(they still land in the Error Log for troubleshooting).
	"""
	try:
		frappe.get_doc(
			{
				"doctype": "Notification Engine Log",
				"notification_rule": notification_rule,
				"channel": channel,
				"status": status,
				"user": user,
				"recipient_address": recipient_address,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"sent_on": frappe.utils.now_datetime(),
				"communication": communication,
				"notification_log": notification_log,
				"subject": subject,
				"content": content,
				"error_message": error_message,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		# rollback just our own failed insert attempt, not anything else
		# already committed/pending from earlier in this request
		frappe.db.rollback()
		frappe.log_error(title="Notification Engine Log failed to write")
