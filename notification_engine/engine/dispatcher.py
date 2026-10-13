import frappe

from notification_engine.notification_engine.doctype.notification_engine_log.notification_engine_log import (
	create_log,
)
from notification_engine.channels import email as email_channel
from notification_engine.channels import sms as sms_channel
from notification_engine.channels import system as system_channel


def dispatch(rule, doc, users):
	"""Render the rule's subject/message once, then fan out to every enabled
	channel for every resolved user. Each (channel, user) attempt is logged
	independently so a failure in one channel never blocks the others.
	"""
	if not users:
		return

	context = {"doc": doc}
	subject = frappe.render_template(rule.subject, context)
	message = frappe.render_template(rule.message, context)

	if rule.send_system_notification:
		_run_channel(
			"System", rule, doc, users, subject, message,
			lambda: system_channel.send(rule, doc, users, subject, message),
		)

	if rule.send_email:
		_run_channel(
			"Email", rule, doc, users, subject, message,
			lambda: email_channel.send(rule, doc, users, subject, message),
		)

	if rule.send_sms:
		_run_channel(
			"SMS", rule, doc, users, subject, message,
			lambda: sms_channel.send(rule, doc, users, subject, message),
		)


def _run_channel(channel_name, rule, doc, users, subject, message, fn):
	"""Runs one channel's send function. The channel itself is responsible
	for per-user success/failure/skip logging (since e.g. SMS may succeed
	for user A but fail for user B due to a missing mobile number); this
	wrapper only catches a total channel failure (e.g. SMS gateway not configured).
	"""
	try:
		fn()
	except Exception as e:
		frappe.log_error(title=f"Notification Engine: {channel_name} channel failed")
		for user in users:
			create_log(
				notification_rule=rule.name,
				channel=channel_name,
				status="Failed",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				subject=subject,
				content=message,
				error_message=str(e),
			)
