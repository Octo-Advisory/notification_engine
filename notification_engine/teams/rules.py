"""Teams channel of a Notification Rule: build the card and queue (or digest) its messages.

Notification Engine has already matched the event, checked the condition and resolved the users.
This sends one message to each of the rule's Teams chats / channels, and a personal message to
each resolved user through the rule's personal destination.
"""

import copy
import hashlib

import frappe

COOLDOWN_KEY = "teams_notify:cooldown:{rule}:{doctype}:{name}"
PERSONAL_TYPES = ("Webhook (Personal via Flow bot)", "Bot (Personal Chat)")
DELETE_EVENT = "On Trash"
# A Role or Department can match many users; cap one event's personal messages.
MAX_RECIPIENTS = 100
LOG_DOCTYPE = "Notification Engine Log"
LOG_SAVEPOINT = "notification_engine_teams_log"


def send(rule, doc, users, subject=None, message=None):
	"""Dispatcher entry point for rules with "Microsoft Teams" ticked."""
	if not rule.get("send_teams") or not frappe.db.get_single_value("Teams Settings", "enabled"):
		return []
	return process_rule(rule, doc, users)


def process_rule(rule, doc, users, *, is_test: bool = False, title_prefix: str = "") -> list[str]:
	"""Queue (or digest) the rule's Teams messages for `doc`. Returns the Teams Message Logs created.

	Test sends skip the cooldown, dedupe and digest, and send personal messages only to the current user.
	"""
	from notification_engine.teams.cards.builder import build_card, make_envelope
	from notification_engine.teams.delivery.digest import add_to_digest
	from notification_engine.teams.delivery.queue import enqueue_message

	if not is_test and in_cooldown(rule, doc):
		return []

	event = rule.event
	card = build_card(rule, doc, title_prefix=title_prefix, event=event)
	digest = not is_test and rule.get("teams_digest") in ("Hourly", "Daily")
	title = _card_title(card)
	logs, buffered = [], False
	bot_card = None

	def card_for(destination):
		"""Bot destinations get the buttons; webhook cards cannot use them."""
		nonlocal bot_card
		has_buttons = rule.get("teams_all_workflow_actions") or rule.get("teams_buttons")
		if not has_buttons or event == DELETE_EVENT or not _is_bot_destination(destination):
			return card
		if bot_card is None:
			from notification_engine.teams.cards.buttons import add_buttons

			bot_card = add_buttons(copy.deepcopy(card), rule, doc, test=is_test)
		return bot_card

	def queue(destination, recipient_user=None, recipient_email=None):
		nonlocal buffered
		if digest:
			add_to_digest(rule, doc, card, destination, recipient_user, recipient_email)
			buffered = True
			return
		target = f"{destination}:{recipient_email}" if recipient_email else destination
		log = enqueue_message(
			destination,
			make_envelope(card_for(destination), recipient=recipient_email),
			title=title,
			rule=rule.name,
			event=event,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			recipient_user=recipient_user,
			recipient_email=recipient_email,
			dedupe_key=None if is_test else make_dedupe_key(rule.name, doc, event, target),
			is_test=is_test,
		)
		if log:
			logs.append(log)
			if not is_test:
				_log(rule, doc, title, recipient_user, recipient_email or destination, log)

	for row in rule.get("teams_destinations") or []:
		if row.destination:
			queue(row.destination)

	personal = rule.get("teams_personal_destination")
	if personal:
		for recipient in _test_recipient() if is_test else get_recipients(rule, doc, users):
			queue(personal, recipient.user, recipient.email)

	if (logs or buffered) and not is_test:
		start_cooldown(rule, doc)
	return logs


def get_recipients(rule, doc, users) -> list[frappe._dict]:
	"""[{user, email}] for enabled users with an email address, capped at MAX_RECIPIENTS."""
	users = [u for u in dict.fromkeys(users or []) if u and u != "Guest"]
	if not users:
		return []
	emails = dict(
		frappe.get_all("User", filters={"name": ("in", users), "enabled": 1}, fields=["name", "email"], as_list=True)
	)
	recipients = [frappe._dict(user=u, email=emails[u]) for u in users if emails.get(u)]
	if len(recipients) > MAX_RECIPIENTS:
		frappe.log_error(
			title=f"Teams Notify: rule {rule.name} has {len(recipients)} recipients",
			message=f"Only the first {MAX_RECIPIENTS} get a personal Teams message.",
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)
		recipients = recipients[:MAX_RECIPIENTS]
	return recipients


def _test_recipient() -> list[frappe._dict]:
	email = frappe.db.get_value("User", frappe.session.user, "email")
	return [frappe._dict(user=frappe.session.user, email=email)] if email else []


def make_dedupe_key(rule_name: str, doc, event: str, target: str) -> str:
	parts = [rule_name, doc.doctype, str(doc.name), event, str(doc.get("modified") or ""), target]
	return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def in_cooldown(rule, doc) -> bool:
	if not rule.get("teams_cooldown_minutes"):
		return False
	# expires=True: never serve this key from the per-request local cache.
	return bool(frappe.cache.get_value(_cooldown_key(rule, doc), expires=True))


def start_cooldown(rule, doc):
	if rule.get("teams_cooldown_minutes"):
		frappe.cache.set_value(
			_cooldown_key(rule, doc), 1, expires_in_sec=int(rule.teams_cooldown_minutes) * 60
		)


def _cooldown_key(rule, doc) -> str:
	return COOLDOWN_KEY.format(rule=rule.name, doctype=doc.doctype, name=doc.name)


def _card_title(card: dict) -> str:
	for block in card.get("body") or []:
		if block.get("type") == "TextBlock" and block.get("text"):
			return block["text"]
	return ""


def _is_bot_destination(destination: str) -> bool:
	dest_type = frappe.db.get_value("Teams Destination", destination, "destination_type", cache=True)
	return bool(dest_type and dest_type.startswith("Bot"))


def _log(rule, doc, title, user, address, teams_message_log):
	"""A "Teams" row in the rule's delivery log, linked to the Teams Message Log with the real status.

	Unlike the other channels' create_log this does not commit: nothing has left the site yet, the
	message is only queued and is delivered after the request commits.
	"""
	frappe.db.savepoint(LOG_SAVEPOINT)
	try:
		frappe.get_doc(
			{
				"doctype": LOG_DOCTYPE,
				"notification_rule": rule.name,
				"channel": "Teams",
				"status": "Queued",
				"user": user,
				"recipient_address": address,
				"reference_doctype": doc.doctype,
				"reference_name": doc.name,
				"sent_on": frappe.utils.now_datetime(),
				"subject": title,
				"teams_message_log": teams_message_log,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.db.rollback(save_point=LOG_SAVEPOINT)
		frappe.log_error(title="Notification Engine Log failed to write (Teams)")
