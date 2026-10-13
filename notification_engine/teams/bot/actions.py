"""Card button clicks: Adaptive Card Universal Actions (invoke `adaptiveCard/action`).

Teams waits about 5 seconds for the response, so only the action itself runs here; updating other
copies of the card happens in a background job.
"""

import json

import frappe
from frappe import _
from frappe.utils import format_datetime, get_fullname, now_datetime, strip_html_tags

from notification_engine.teams.cards.buttons import VERB, find_button

CARD = "application/vnd.microsoft.card.adaptive"
MESSAGE = "application/vnd.microsoft.activity.message"
LOCK_SECONDS = 30


def on_card_action(activity: dict) -> dict:
	action = ((activity.get("value") or {}).get("action")) or {}
	if action.get("verb") != VERB:
		return message(_("This button is not handled by ERP."))
	data = action.get("data") or {}
	if data.get("test"):
		return message(_("This is a test card. Nothing was changed in ERP."))

	doctype, name, key = data.get("doctype"), data.get("name"), data.get("key")
	if not (doctype and name and key and data.get("rule")):
		return message(_("This button is missing its details."))

	user = clicking_user(activity)
	if not user:
		return message(_("Your Teams account isn't linked to ERP. Ask your ERP admin to link it in Teams User Map."))

	lock = f"teams_notify:action_lock:{frappe.local.site}:{doctype}:{name}"
	if not frappe.cache.set(lock, user, nx=True, ex=LOCK_SECONDS):
		return message(_("Someone is already acting on {0}. Try again in a moment.").format(name))

	from notification_engine.teams.install import BOT_USER

	try:
		frappe.set_user(user)
		return run_action(activity, data, user)
	finally:
		frappe.set_user(BOT_USER)
		frappe.cache.delete(lock)


def run_action(activity: dict, data: dict, user: str) -> dict:
	doctype, name = data["doctype"], data["name"]
	if not frappe.db.exists(doctype, name):
		return message(_("{0} {1} no longer exists.").format(_(doctype), name))
	if not frappe.db.exists("Notification Rule", data["rule"]):
		return message(_("The notification rule for this card no longer exists."))

	rule = frappe.get_doc("Notification Rule", data["rule"])
	doc = frappe.get_doc(doctype, name)
	# Write/submit/cancel permissions are enforced by Frappe when the action saves the document.
	if not frappe.has_permission(doctype, "read", doc, user=user):
		return message(_("You don't have permission to open {0} {1}.").format(_(doctype), name))

	button = find_button(rule, doc, data["key"])
	if not button:
		# The document moved on (e.g. already approved) or the rule changed.
		return refreshed_card(rule, doc, already_done_text(doc))

	comment = (data.get("comment") or "").strip()
	if button.comment_required and not comment:
		return message(_("Please enter a comment."))

	if button.key.startswith("wf:") and button.key[3:] not in allowed_actions(doc):
		return message(_("You are not allowed to {0} {1}.").format(_(button.key[3:]), name))

	try:
		if button.key.startswith("wf:"):
			outcome = do_workflow_action(doc, button.key[3:])
		else:
			outcome = do_set_value(doc, button.row)
	except (frappe.ValidationError, frappe.PermissionError) as e:
		frappe.db.rollback(save_point="teams_bot_activity")
		frappe.clear_last_message()
		return message(_("ERP did not accept this: {0}").format(strip_html_tags(str(e)) or type(e).__name__))

	doc.reload()
	when = format_datetime(now_datetime(), "dd-MM-yyyy HH:mm")
	note = _("{0} from Microsoft Teams by {1}").format(outcome, get_fullname(user))
	doc.add_comment("Comment", f"{note}{(': ' + frappe.utils.escape_html(comment)) if comment else ''}")

	status = _("✅ {0} by {1} at {2}").format(outcome, get_fullname(user), when)
	if comment:
		status += f"\n\n{_('Comment')}: {comment}"
	card = refreshed_card(rule, doc, status, as_card=True)
	queue_copy_updates(rule.name, doc, activity, card)
	return {"statusCode": 200, "type": CARD, "value": card}


def allowed_actions(doc) -> list[str]:
	"""Workflow actions the current user may take (roles and transition conditions)."""
	from frappe.model.workflow import get_transitions

	try:
		return [t.action for t in get_transitions(doc)]
	except frappe.PermissionError:
		return []


def do_workflow_action(doc, action: str) -> str:
	from frappe.model.workflow import apply_workflow

	result = apply_workflow(doc.as_dict(), action)
	if result is None:
		return _("{0} (queued for submission)").format(_(action))
	return _(action)


def do_set_value(doc, row) -> str:
	from notification_engine.teams.templates import get_context, render

	value = render(row.value or "", get_context(doc)) if row.value else None
	doc.set(row.fieldname, value)
	doc.save()
	label = _(doc.meta.get_label(row.fieldname))
	return row.label or _("{0} set to {1}").format(label, doc.get_formatted(row.fieldname) or value)


def clicking_user(activity: dict) -> str | None:
	sender = activity.get("from") or {}
	name = None
	if sender.get("aadObjectId"):
		name = frappe.db.get_value("Teams User Map", {"aad_object_id": sender["aadObjectId"]}, "user")
	if not name and sender.get("id"):
		name = frappe.db.get_value("Teams User Map", {"teams_user_id": sender["id"]}, "user")
	if name and frappe.db.get_value("User", name, "enabled"):
		return name
	return None


def already_done_text(doc) -> str:
	from frappe.model.workflow import get_workflow_name

	workflow_name = get_workflow_name(doc.doctype)
	state_field = frappe.db.get_value("Workflow", workflow_name, "workflow_state_field") if workflow_name else None
	state = doc.get(state_field) if state_field else None
	who = get_fullname(doc.modified_by)
	if state:
		return _("Already {0} (last changed by {1}).").format(_(state), who)
	return _("This card is out of date (last changed by {0}).").format(who)


def refreshed_card(rule, doc, status_text: str, as_card: bool = False):
	"""The rule's card for the current document, without buttons, with a status line."""
	from notification_engine.teams.cards.builder import build_card

	card = build_card(rule, doc)
	card["body"].append(
		{"type": "TextBlock", "text": status_text, "wrap": True, "weight": "Bolder", "color": "Good", "spacing": "Medium"}
	)
	card["actions"] = [a for a in card.get("actions") or [] if a.get("type") == "Action.OpenUrl"]
	return card if as_card else {"statusCode": 200, "type": CARD, "value": card}


def message(text: str) -> dict:
	return {"statusCode": 200, "type": MESSAGE, "value": text}


def queue_copy_updates(rule: str, doc, activity: dict, card: dict):
	"""Replace the buttons on every other bot copy of this card (other chats, other approvers)."""
	clicked = activity.get("replyToId")
	logs = frappe.get_all(
		"Teams Message Log",
		filters={
			"rule": rule,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"status": "Sent",
			"activity_id": ("is", "set"),
		},
		fields=["name", "activity_id"],
	)
	names = [l.name for l in logs if l.activity_id != clicked]
	if names:
		frappe.enqueue(
			"notification_engine.teams.bot.actions.update_card_copies",
			log_names=names,
			card=card,
			enqueue_after_commit=True,
		)


def update_card_copies(log_names: list[str], card: dict):
	"""Job: PUT the updated card over each logged bot message."""
	from notification_engine.teams.cards.builder import make_envelope
	from notification_engine.teams.delivery.base import OutboundMessage
	from notification_engine.teams.delivery.bot import BotSender, find_user_map

	sender = BotSender()
	for name in log_names:
		log = frappe.get_doc("Teams Message Log", name)
		if not log.destination or not frappe.db.exists("Teams Destination", log.destination):
			continue
		destination = frappe.get_doc("Teams Destination", log.destination)
		if not destination.destination_type.startswith("Bot"):
			continue
		service_url = destination.service_url
		if destination.destination_type == "Bot (Personal Chat)":
			user_map = find_user_map(log.recipient_user, log.recipient_email)
			service_url = user_map.service_url if user_map else None
		message = OutboundMessage(
			log_name=log.name,
			destination=destination,
			payload=make_envelope(card),
			conversation_id=log.conversation_id,
			service_url=service_url,
		)
		result = sender.update(message, log.activity_id)
		if not result.ok:
			frappe.log_error(
				title="Teams Notify: could not update a card copy",
				message=result.error or "",
				reference_doctype="Teams Message Log",
				reference_name=log.name,
			)
		else:
			log.db_set("payload", json.dumps(make_envelope(card), ensure_ascii=False, indent=1), update_modified=False)
