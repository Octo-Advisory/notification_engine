"""Build Adaptive Cards (v1.4) and the Workflows webhook envelope."""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_fullname, get_url, strip_html_tags
from frappe.utils.data import quoted, slug

from notification_engine.teams.templates import get_context, render

CARD_VERSION = "1.4"
ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"
# Workflows reject messages over 28 KB. Keep headroom for the envelope and recipient.
MAX_PAYLOAD_BYTES = 28 * 1024
MAX_CARD_BYTES = MAX_PAYLOAD_BYTES - 1024
MAX_FACT_VALUE_CHARS = 500
TITLE_COLORS = {"Accent", "Good", "Warning", "Attention"}
USER_FIELDS = {"owner", "modified_by"}


def get_site_url() -> str:
	site_url = frappe.db.get_single_value("Teams Settings", "site_url")
	return (site_url or get_url()).rstrip("/")


def get_doc_url(doctype: str, name: str) -> str:
	return f"{get_site_url()}/app/{quoted(slug(doctype))}/{quoted(name)}"


def build_card(rule, doc, title_prefix: str = "", event: str | None = None) -> dict:
	"""Build the Teams card for a Notification Rule and `doc`. `rule` can be a Document or a dict.

	Teams Title / Body fall back to the rule's Subject and Message (HTML converted to Markdown, which
	is what Teams cards show), so one rule can serve email and Teams without writing the text twice.
	"""
	# frappe._dict answers every attribute, so check the type rather than hasattr().
	rule = frappe._dict(rule.as_dict() if isinstance(rule, Document) else rule)
	context = get_context(doc)

	if (rule.teams_card_template or "").strip():
		card = json.loads(render(rule.teams_card_template, context))
		if title_prefix:
			_prefix_first_text(card, title_prefix)
		return enforce_size(card)

	title = render(rule.teams_title or rule.subject, context).strip() or f"{_(doc.doctype)}: {doc.name}"
	if (rule.teams_body or "").strip():
		text = render(rule.teams_body, context).strip()
	else:
		text = (frappe.utils.to_markdown(render(rule.message, context)) or "").strip()
	return make_card(
		title=f"{title_prefix}{title}",
		text=text,
		facts=get_facts(doc, rule.teams_fields or []),
		color=rule.teams_title_color,
		open_url=get_doc_url(doc.doctype, doc.name)
		if rule.teams_include_open_button and (event or rule.event) != "On Trash"
		else None,
	)


def make_card(
	title: str,
	text: str | None = None,
	facts: list[dict] | None = None,
	color: str | None = None,
	open_url: str | None = None,
) -> dict:
	title_block = {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True}
	if color in TITLE_COLORS:
		title_block["color"] = color

	body = [title_block]
	if text:
		body.append({"type": "TextBlock", "text": text, "wrap": True})
	if facts:
		body.append({"type": "FactSet", "facts": facts})

	card = {
		"type": "AdaptiveCard",
		"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
		"version": CARD_VERSION,
		"body": body,
	}
	if open_url:
		card["actions"] = [{"type": "Action.OpenUrl", "title": _("Open in Frappe"), "url": open_url}]
	return enforce_size(card)


def get_facts(doc, field_rows) -> list[dict]:
	"""Facts for allow-listed fields only. Empty values are left out."""
	meta = frappe.get_meta(doc.doctype)
	facts = []
	for row in field_rows:
		row = frappe._dict(row)
		fieldname = row.fieldname
		if not fieldname:
			continue
		value = format_field(doc, fieldname)
		if value in (None, ""):
			continue
		label = row.label or meta.get_label(fieldname)
		facts.append({"title": _(label), "value": value})
	return facts


def format_field(doc, fieldname: str) -> str | None:
	raw = doc.get(fieldname)
	if raw in (None, ""):
		return None
	df = doc.meta.get_field(fieldname)
	if fieldname in USER_FIELDS or (df and df.fieldtype == "Link" and df.options == "User"):
		value = get_fullname(raw)
	elif fieldname == "name":
		value = str(raw)
	else:
		value = doc.get_formatted(fieldname)
	value = strip_html_tags(str(value or "")).strip()
	if len(value) > MAX_FACT_VALUE_CHARS:
		value = value[: MAX_FACT_VALUE_CHARS - 1] + "…"
	return value


def card_size(card: dict) -> int:
	return len(json.dumps(card, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def enforce_size(card: dict) -> dict:
	"""Drop facts (then trim long text) until the card fits the Workflows limit."""
	if card_size(card) <= MAX_CARD_BYTES:
		return card

	note = {
		"type": "TextBlock",
		"text": _("Open in Frappe for full details."),
		"isSubtle": True,
		"wrap": True,
	}
	card.setdefault("body", []).append(note)

	factsets = [b for b in card["body"] if b.get("type") == "FactSet"]
	for factset in reversed(factsets):
		while factset["facts"] and card_size(card) > MAX_CARD_BYTES:
			factset["facts"].pop()
		if not factset["facts"]:
			card["body"].remove(factset)
		if card_size(card) <= MAX_CARD_BYTES:
			return card

	# Still too large: trim text blocks, longest first.
	for block in sorted(
		(b for b in card["body"] if b.get("type") == "TextBlock" and b is not note),
		key=lambda b: len(b.get("text", "")),
		reverse=True,
	):
		while card_size(card) > MAX_CARD_BYTES and len(block["text"]) > 100:
			excess = card_size(card) - MAX_CARD_BYTES
			keep = max(100, len(block["text"]) - excess - 10)
			block["text"] = block["text"][:keep] + "…"
		if card_size(card) <= MAX_CARD_BYTES:
			return card

	if card_size(card) > MAX_CARD_BYTES:
		frappe.throw(_("Teams card is larger than 28 KB even after truncation."))
	return card


def make_envelope(card: dict, recipient: str | None = None) -> dict:
	"""Workflows webhook payload. `recipient` is read by Flow-bot personal-message flows."""
	envelope = {
		"type": "message",
		"attachments": [{"contentType": ADAPTIVE_CARD_CONTENT_TYPE, "contentUrl": None, "content": card}],
	}
	if recipient:
		envelope["recipient"] = recipient
	return envelope


def _prefix_first_text(card: dict, prefix: str):
	for block in card.get("body") or []:
		if block.get("type") == "TextBlock" and block.get("text"):
			block["text"] = prefix + block["text"]
			return
