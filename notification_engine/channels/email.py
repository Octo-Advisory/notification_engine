import frappe

from notification_engine.engine.condition import evaluate_condition
from notification_engine.notification_engine.doctype.notification_engine_log.notification_engine_log import (
	create_log,
)

DEFAULT_MODE = "Individual Emails"


def send(rule, doc, users, subject, message):
	valid_emails, missing_users = _resolve_user_emails(users)

	for user in missing_users:
		create_log(
			notification_rule=rule.name,
			channel="Email",
			status="Skipped",
			user=user,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			subject=subject,
			content=message,
			error_message="No email address on User record",
		)

	if not valid_emails:
		return

	cc_emails = _resolve_cc_bcc(rule.cc_recipients, doc)
	bcc_emails = _resolve_cc_bcc(rule.bcc_recipients, doc)

	mode = rule.email_delivery_mode or DEFAULT_MODE

	if mode == "Individual Emails":
		_send_individual(rule, doc, valid_emails, subject, message, cc_emails, bcc_emails)
	elif mode == "Single Email (To)":
		_send_single(rule, doc, valid_emails, subject, message, cc_emails, bcc_emails, put_users_in="to")
	elif mode == "Single Email (BCC)":
		_send_single(rule, doc, valid_emails, subject, message, cc_emails, bcc_emails, put_users_in="bcc")
	else:
		# unknown/unset mode - fail safe to the credit-friendly default rather
		# than silently reverting to one-email-per-person
		_send_single(rule, doc, valid_emails, subject, message, cc_emails, bcc_emails, put_users_in="bcc")


def _send_individual(rule, doc, valid_emails, subject, message, cc_emails, bcc_emails):
	"""One send per recipient. Uses one send credit per person - only choose
	this mode when the provider's quota isn't a concern, or when recipients
	genuinely must not see each other's email addresses and you don't want
	to rely on BCC.
	"""
	for user, email in valid_emails.items():
		try:
			communication_name = _sendmail_and_get_communication(
				recipients=[email], cc=cc_emails, bcc=bcc_emails,
				subject=subject, message=message, doc=doc,
			)
			create_log(
				notification_rule=rule.name,
				channel="Email",
				status="Success",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				recipient_address=email,
				communication=communication_name,
			)
		except Exception as e:
			create_log(
				notification_rule=rule.name,
				channel="Email",
				status="Failed",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				subject=subject,
				content=message,
				recipient_address=email,
				error_message=str(e),
			)


def _send_single(rule, doc, valid_emails, subject, message, cc_emails, bcc_emails, put_users_in):
	"""One send total, regardless of how many recipients - this is the
	credit-friendly mode. `put_users_in` controls whether the target users
	end up visible in To (they can see each other) or hidden in Bcc
	(default recommendation for anything beyond a small internal group).

	Frappe creates exactly one Communication record for this one send - all
	targeted users' log rows point to that same Communication, which
	accurately reflects reality: it genuinely was one email, not several.
	"""
	target_emails = list(valid_emails.values())

	if put_users_in == "to":
		to_list = target_emails
		final_bcc = bcc_emails
	else:
		to_list = [_get_placeholder_to_address(rule)]
		# de-duplicate in case a target user is also in the static bcc list
		final_bcc = list(dict.fromkeys(bcc_emails + target_emails))

	try:
		communication_name = _sendmail_and_get_communication(
			recipients=to_list, cc=cc_emails, bcc=final_bcc,
			subject=subject, message=message, doc=doc,
		)
		for user, email in valid_emails.items():
			create_log(
				notification_rule=rule.name,
				channel="Email",
				status="Success",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				recipient_address=email,
				communication=communication_name,
			)
	except Exception as e:
		for user, email in valid_emails.items():
			create_log(
				notification_rule=rule.name,
				channel="Email",
				status="Failed",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				subject=subject,
				content=message,
				recipient_address=email,
				error_message=str(e),
			)


def _sendmail_and_get_communication(recipients, cc, bcc, subject, message, doc):
	"""Sends via frappe.sendmail (same primitive core Notification uses) and
	looks up the Communication record Frappe just created for it, so our log
	can link to it rather than storing a second copy of the email body.

	frappe.sendmail() doesn't return the Communication name directly when
	reference_doctype/reference_name are supplied, so we fetch the most
	recently created outgoing Communication against this reference right
	after sending - safe here because this call and the lookup are
	synchronous with no concurrent sends against the same document in
	between.
	"""
	frappe.sendmail(
		recipients=recipients,
		cc=cc,
		bcc=bcc,
		subject=subject,
		message=message,
		reference_doctype=doc.doctype,
		reference_name=doc.name,
	)

	return frappe.db.get_value(
		"Communication",
		{
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"sent_or_received": "Sent",
		},
		"name",
		order_by="creation desc",
	)


def _get_placeholder_to_address(rule):
	if rule.single_email_to_address:
		return rule.single_email_to_address

	default_outgoing = frappe.db.get_single_value("Email Account", "email_id")
	if default_outgoing:
		return default_outgoing

	site_default = frappe.db.get_default("email_sender") or frappe.db.get_default("auto_email_id")
	if site_default:
		return site_default

	# last resort - Administrator's email, always present on a Frappe site
	return frappe.db.get_value("User", "Administrator", "email") or "notifications@localhost"


def _resolve_user_emails(users):
	rows = frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "email"])
	email_by_user = {row.name: row.email for row in rows}

	valid = {}
	missing = []
	for user in users:
		email = email_by_user.get(user)
		if email:
			valid[user] = email
		else:
			missing.append(user)
	return valid, missing


def _resolve_cc_bcc(rows, doc):
	"""Resolve a CC or BCC child table into a deduplicated list of emails.
	Each row's own `condition` (if set) is evaluated independently, so a
	single rule can CC Finance only when doc.grand_total is large, while
	always CC-ing a manager regardless of amount, for example.
	"""
	if not rows:
		return []

	eligible_users = []
	for row in rows:
		if not row.is_enabled:
			continue
		if row.condition and not evaluate_condition(row.condition, doc):
			continue
		eligible_users.append(row.user)

	if not eligible_users:
		return []

	user_rows = frappe.get_all(
		"User", filters={"name": ["in", eligible_users]}, fields=["name", "email"]
	)
	emails = [r.email for r in user_rows if r.email]
	return list(dict.fromkeys(emails))  # de-duplicate, preserve order
