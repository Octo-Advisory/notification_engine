import frappe

from notification_engine.notification_engine.doctype.notification_engine_log.notification_engine_log import (
	create_log,
)


def send(rule, doc, users, subject, message):
	"""Frappe's core Notification Log already targets a single user correctly
	via its `for_user` field - the bug in ERPNext's workflow notifications is
	entirely in *how the recipient list is built*, not in this primitive. We
	just reuse it here with our own resolved user list.
	"""
	for user in users:
		try:
			notification_doc = frappe.new_doc("Notification Log")
			notification_doc.for_user = user
			notification_doc.type = "Alert"
			notification_doc.document_type = doc.doctype
			notification_doc.document_name = doc.name
			notification_doc.subject = subject
			notification_doc.email_content = message
			notification_doc.from_user = frappe.session.user
			notification_doc.insert(ignore_permissions=True)

			create_log(
				notification_rule=rule.name,
				channel="System",
				status="Success",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				notification_log=notification_doc.name,
			)
		except Exception as e:
			create_log(
				notification_rule=rule.name,
				channel="System",
				status="Failed",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				subject=subject,
				content=message,
				error_message=str(e),
			)
