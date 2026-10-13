"""Digest rules buffer events and send one summary card per period."""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import now_datetime

MAX_ITEMS = 20


def period_key(frequency: str, at=None) -> str:
	at = at or now_datetime()
	return f"{frequency}:{at.strftime('%Y-%m-%d %H' if frequency == 'Hourly' else '%Y-%m-%d')}"


def add_to_digest(
	rule, doc, card: dict, destination: str, recipient_user: str | None = None, recipient_email: str | None = None
):
	"""Buffer one event. A document appears once per digest; later events update its line."""
	key = period_key(rule.teams_digest)
	summary = json.dumps(
		{"title": _first_text(card), "url": _open_url(card), "event": rule.event},
		ensure_ascii=False,
	)
	filters = {
		"rule": rule.name,
		"destination": destination,
		"recipient_user": recipient_user,
		"recipient_email": recipient_email,
		"reference_doctype": doc.doctype,
		"reference_name": doc.name,
		"period_key": key,
	}
	existing = frappe.db.get_value("Teams Digest Buffer", filters)
	if existing:
		frappe.db.set_value("Teams Digest Buffer", existing, "summary", summary)
		return existing
	return (
		frappe.get_doc({"doctype": "Teams Digest Buffer", **filters, "summary": summary})
		.insert(ignore_permissions=True, ignore_links=True)
		.name
	)


def flush_hourly():
	flush("Hourly")


def flush_daily():
	flush("Daily")


def flush(frequency: str, now=None):
	"""Send every buffered group from finished periods of `frequency`, then delete the rows."""
	from notification_engine.teams.cards.builder import enforce_size, make_card, make_envelope
	from notification_engine.teams.delivery.queue import enqueue_message

	current = period_key(frequency, now)
	rows = frappe.get_all(
		"Teams Digest Buffer",
		filters=[["period_key", "like", f"{frequency}:%"], ["period_key", "<", current]],
		fields=[
			"name",
			"rule",
			"destination",
			"recipient_user",
			"recipient_email",
			"period_key",
			"summary",
			"reference_doctype",
		],
		order_by="creation asc",
	)
	groups: dict[tuple, list] = {}
	for row in rows:
		key = (row.rule, row.destination, row.recipient_user, row.recipient_email, row.period_key)
		groups.setdefault(key, []).append(row)

	for (rule_name, destination, recipient_user, recipient_email, key), items in groups.items():
		rule_title = frappe.db.get_value("Notification Rule", rule_name, "title") or rule_name
		card = make_card(title=_("{0}: {1} update(s)").format(rule_title, len(items)), color="Accent")
		# One TextBlock per item: markdown lists render inconsistently across Teams clients.
		for item in items[:MAX_ITEMS]:
			summary = json.loads(item.summary or "{}")
			title = (summary.get("title") or item.name).replace("[", "(").replace("]", ")")
			text = f"• [{title}]({summary['url']})" if summary.get("url") else f"• {title}"
			card["body"].append({"type": "TextBlock", "text": text, "wrap": True, "spacing": "Small"})
		if len(items) > MAX_ITEMS:
			card["body"].append(
				{"type": "TextBlock", "text": _("and {0} more").format(len(items) - MAX_ITEMS), "isSubtle": True}
			)
		card = enforce_size(card)
		enqueue_message(
			destination,
			make_envelope(card, recipient=recipient_email),
			title=_("Digest: {0} ({1} items)").format(rule_title, len(items)),
			rule=rule_name,
			event="Digest",
			reference_doctype=items[0].reference_doctype,
			recipient_user=recipient_user,
			recipient_email=recipient_email,
			dedupe_key=hashlib.sha1(
				"|".join(["digest", rule_name, destination or "", recipient_email or "", key]).encode()
			).hexdigest(),
		)
		frappe.db.delete("Teams Digest Buffer", {"name": ("in", [i.name for i in items])})


def _first_text(card: dict) -> str:
	for block in card.get("body") or []:
		if block.get("type") == "TextBlock" and block.get("text"):
			return block["text"]
	return ""


def _open_url(card: dict) -> str | None:
	for action in card.get("actions") or []:
		if action.get("type") == "Action.OpenUrl":
			return action.get("url")
	return None
