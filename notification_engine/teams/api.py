"""Public Python API and whitelisted methods used by the Teams Notify forms."""

import frappe
from frappe import _

from notification_engine.teams.cards.builder import get_doc_url, make_card, make_envelope
from notification_engine.teams.delivery.queue import enqueue_message
from notification_engine.teams.delivery.queue import resend as _resend

ADMIN_ROLES = ("System Manager", "Teams Admin")
TEST_PREFIX = "[TEST] "
PERSONAL_TYPES = ("Webhook (Personal via Flow bot)", "Bot (Personal Chat)")


def send_to_teams(
	destination: str,
	card: dict | None = None,
	text: str | None = None,
	recipient_user: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	title: str | None = None,
) -> str | None:
	"""Queue a message to a Teams Destination from your own code. Returns the Teams Message Log name.

	Pass either a full Adaptive Card (`card`) or plain `text` (with an optional `title`).
	Delivery runs in the background after the current transaction commits.
	"""
	dest_type = frappe.db.get_value("Teams Destination", destination, "destination_type")
	if not dest_type:
		frappe.throw(_("Teams Destination {0} does not exist.").format(destination))
	if not card and not text and not title:
		frappe.throw(_("Pass a card, or text and/or a title."))

	if not card:
		open_url = get_doc_url(reference_doctype, reference_name) if reference_doctype and reference_name else None
		card = make_card(title=title or text, text=text if title else None, open_url=open_url)

	recipient_email = None
	if dest_type in PERSONAL_TYPES:
		if not recipient_user:
			frappe.throw(_("{0} is a personal webhook. Pass recipient_user.").format(destination))
		recipient_email = frappe.db.get_value("User", recipient_user, "email") or recipient_user

	return enqueue_message(
		destination,
		make_envelope(card, recipient=recipient_email if dest_type == PERSONAL_TYPES[0] else None),
		title=title or (text or "")[:140],
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		recipient_user=recipient_user if frappe.db.exists("User", recipient_user or "") else None,
		recipient_email=recipient_email,
	)


@frappe.whitelist()
def send_test_to_destination(destination: str) -> str | None:
	frappe.only_for(ADMIN_ROLES)
	dest = frappe.get_doc("Teams Destination", destination)
	recipient = None
	if dest.destination_type in PERSONAL_TYPES:
		recipient = frappe.db.get_value("User", frappe.session.user, "email")
		if not recipient:
			frappe.throw(_("Your user has no email address to send the personal test message to."))

	card = make_card(
		title=f"{TEST_PREFIX}{_('Teams Notify test message')}",
		text=_("Sent from {0} by {1}. If you can see this, the destination works.").format(
			frappe.utils.get_url(), frappe.utils.get_fullname(frappe.session.user)
		),
		color="Accent",
		open_url=frappe.utils.get_url_to_form("Teams Destination", dest.name),
	)
	return enqueue_message(
		dest.name,
		make_envelope(card, recipient=recipient if dest.destination_type == PERSONAL_TYPES[0] else None),
		title=_("Test message to {0}").format(dest.name),
		recipient_user=frappe.session.user if recipient else None,
		recipient_email=recipient,
		is_test=True,
	)


@frappe.whitelist()
def send_test_for_rule(rule: str, docname: str | None = None) -> dict:
	"""Render a Notification Rule's Teams card against a document and send it with a [TEST] prefix.

	Goes to the rule's Teams chats / channels, and to the current user through its personal
	destination. The condition is not applied, but its result is reported so the admin can check it.
	"""
	from notification_engine.notification_engine.doctype.notification_rule.notification_rule import (
		get_sample_doc,
	)
	from notification_engine.teams.rules import process_rule

	frappe.only_for(ADMIN_ROLES)
	rule_doc = frappe.get_doc("Notification Rule", rule)
	if not rule_doc.send_teams or not (rule_doc.teams_destinations or rule_doc.teams_personal_destination):
		frappe.throw(_("This rule has no Teams chats, channels or personal destination to test."))

	doc = get_sample_doc(rule_doc.reference_doctype, docname or None)
	try:
		condition_result = bool(frappe.safe_eval(rule_doc.condition, None, {"doc": doc})) if rule_doc.condition else True
		condition_error = None
	except Exception as e:
		condition_result, condition_error = None, str(e)

	logs = process_rule(rule_doc, doc, [], is_test=True, title_prefix=TEST_PREFIX)
	return {
		"logs": logs,
		"docname": doc.name,
		"condition": condition_result,
		"condition_error": condition_error,
	}


@frappe.whitelist()
def resend(names) -> int:
	"""Resend one or more Teams Message Logs. `names` is a name or a JSON list of names."""
	frappe.only_for(ADMIN_ROLES)
	names = frappe.parse_json(names) if isinstance(names, str) and names.startswith("[") else names
	if isinstance(names, str):
		names = [names]
	count = 0
	for name in names:
		if frappe.db.get_value("Teams Message Log", name, "status") not in (None, "Queued"):
			_resend(name)
			count += 1
	return count


@frappe.whitelist()
def get_log_status(names) -> list[dict]:
	"""Status of logs, for the forms that wait for a test message to be delivered."""
	frappe.only_for(ADMIN_ROLES)
	names = frappe.parse_json(names) if isinstance(names, str) and names.startswith("[") else [names]
	return frappe.get_all(
		"Teams Message Log",
		filters={"name": ("in", names)},
		fields=["name", "status", "destination", "http_status", "error"],
	)


@frappe.whitelist()
def check_bot_connection() -> str:
	"""Get a Bot Connector token with the saved credentials (no message is sent)."""
	from notification_engine.teams.bot.auth import BotAuthError, get_access_token

	frappe.only_for(ADMIN_ROLES)
	try:
		get_access_token(force_refresh=True)
	except BotAuthError as e:
		frappe.throw(str(e), title=_("Bot connection failed"))
	return _("Connected: Microsoft issued a token for this bot.")


@frappe.whitelist()
def download_app_package():
	"""Download the Teams app package for Teams Admin Center."""
	from notification_engine.teams.teams_manifest.builder import PACKAGE_NAME, build_package

	frappe.only_for(ADMIN_ROLES)
	frappe.local.response.filename = PACKAGE_NAME
	frappe.local.response.filecontent = build_package()
	frappe.local.response.type = "download"
