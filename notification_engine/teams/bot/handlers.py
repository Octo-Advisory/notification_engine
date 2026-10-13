"""Handle activities from the Bot Connector. Anything slow runs in background jobs."""

import frappe
from frappe import _
from frappe.utils import now_datetime

from notification_engine.teams.bot import auth, connector

BOT_CONVERSATION = "Bot Conversation"
CARD_ACTION = "adaptiveCard/action"


def dispatch(activity: dict) -> dict | None:
	"""Returns the invoke response body for invoke activities, else None."""
	kind = activity.get("type")
	if kind == "installationUpdate":
		on_installation_update(activity)
	elif kind == "conversationUpdate":
		on_conversation_update(activity)
	elif kind == "message":
		on_message(activity)
	elif kind == "invoke" and activity.get("name") == CARD_ACTION:
		from notification_engine.teams.bot.actions import on_card_action

		return on_card_action(activity)
	elif kind == "invoke":
		return {"statusCode": 200, "type": "application/vnd.microsoft.activity.message", "value": ""}
	return None


def on_installation_update(activity: dict):
	action = activity.get("action") or ""
	if action.startswith("add"):
		register_conversation(activity)
	elif action.startswith("remove"):
		unregister_conversation(activity)


def on_conversation_update(activity: dict):
	bot_id = (activity.get("recipient") or {}).get("id")
	if any(m.get("id") == bot_id for m in activity.get("membersAdded") or []):
		register_conversation(activity)
	if any(m.get("id") == bot_id for m in activity.get("membersRemoved") or []):
		unregister_conversation(activity)


def on_message(activity: dict):
	conversation = activity.get("conversation") or {}
	if conversation.get("conversationType") == "personal":
		register_conversation(activity)  # someone chatting with the bot has it installed
	frappe.enqueue(
		"notification_engine.teams.bot.handlers.send_help_reply",
		service_url=activity.get("serviceUrl"),
		conversation_id=conversation.get("id"),
		activity_id=activity.get("id"),
		enqueue_after_commit=True,
	)


def register_conversation(activity: dict):
	conversation = activity.get("conversation") or {}
	if conversation.get("conversationType") == "personal":
		upsert_user_map(activity, installed=True)
	else:
		upsert_bot_destination(activity)


def unregister_conversation(activity: dict):
	conversation = activity.get("conversation") or {}
	if conversation.get("conversationType") == "personal":
		user_map = _user_map_for(activity.get("from") or {})
		if user_map:
			frappe.db.set_value("Teams User Map", user_map, {"installed": 0, "last_seen": now_datetime()})
	else:
		name = frappe.db.get_value("Teams Destination", {"conversation_id": _destination_conversation_id(activity)})
		if name:
			frappe.db.set_value("Teams Destination", name, "enabled", 0)


# ---------------------------------------------------------------- personal


def upsert_user_map(activity: dict, installed: bool) -> str | None:
	sender = activity.get("from") or {}
	if not sender.get("aadObjectId") and not sender.get("id"):
		return None
	values = {
		"teams_user_id": sender.get("id"),
		"teams_name": sender.get("name"),
		"conversation_id": (activity.get("conversation") or {}).get("id"),
		"service_url": activity.get("serviceUrl"),
		"installed": int(installed),
		"last_seen": now_datetime(),
	}
	name = _user_map_for(sender)
	if name:
		frappe.db.set_value("Teams User Map", name, values)
	else:
		name = (
			frappe.get_doc({"doctype": "Teams User Map", "aad_object_id": sender.get("aadObjectId"), **values})
			.insert(ignore_permissions=True)
			.name
		)
	if not frappe.db.get_value("Teams User Map", name, "user"):
		frappe.enqueue("notification_engine.teams.bot.handlers.link_user", user_map=name, enqueue_after_commit=True)
	return name


def _user_map_for(sender: dict) -> str | None:
	if sender.get("aadObjectId"):
		name = frappe.db.get_value("Teams User Map", {"aad_object_id": sender["aadObjectId"]})
		if name:
			return name
	if sender.get("id"):
		return frappe.db.get_value("Teams User Map", {"teams_user_id": sender["id"]})
	return None


def link_user(user_map: str):
	"""Job: read the member's email/UPN from Teams and link the map to the Frappe user with that email."""
	doc = frappe.get_doc("Teams User Map", user_map)
	if not (doc.conversation_id and doc.teams_user_id):
		return
	response = connector.get_member(
		doc.service_url or auth.get_bot_settings().service_url, doc.conversation_id, doc.teams_user_id
	)
	if not response.ok:
		frappe.log_error(title="Teams Notify: could not read Teams member", message=response.error)
		return
	email = (response.data.get("email") or response.data.get("userPrincipalName") or "").strip()
	if email:
		doc.teams_email = email
	if not doc.user and email:
		user = frappe.db.get_value("User", {"email": email, "enabled": 1}) or frappe.db.get_value(
			"User", {"name": email, "enabled": 1}
		)
		if user and not frappe.db.exists("Teams User Map", {"user": user, "name": ("!=", doc.name)}):
			doc.user = user
	doc.save(ignore_permissions=True)


# ---------------------------------------------------------------- group chats and channels


def _destination_conversation_id(activity: dict) -> str | None:
	return (activity.get("conversation") or {}).get("id")


def upsert_bot_destination(activity: dict) -> str | None:
	"""Create (disabled) or refresh the Bot Conversation destination for a group chat or channel."""
	conversation = activity.get("conversation") or {}
	channel_data = activity.get("channelData") or {}
	conversation_id = _destination_conversation_id(activity)
	if not conversation_id:
		return None

	team = channel_data.get("team") or {}
	channel = channel_data.get("channel") or (channel_data.get("settings") or {}).get("selectedChannel") or {}
	is_channel = conversation.get("conversationType") == "channel"
	values = {
		"conversation_type": "channel" if is_channel else "groupChat",
		"conversation_id": conversation_id,
		"service_url": activity.get("serviceUrl"),
		"team_id": team.get("id"),
		"channel_id": channel.get("id"),
		"conversation_name": conversation.get("name") or channel.get("name") or team.get("name"),
	}
	existing = frappe.db.get_value("Teams Destination", {"conversation_id": conversation_id})
	if existing:
		frappe.db.set_value("Teams Destination", existing, values)
		return existing

	base = values["conversation_name"] or (
		_("Teams channel") if is_channel else _("Teams group chat")
	)
	if is_channel and team.get("name") and team.get("name") != base:
		base = f"{team['name']} / {base}"
	name = _unique_name(f"{base} (bot)")
	doc = frappe.get_doc(
		{
			"doctype": "Teams Destination",
			"destination_name": name,
			"destination_type": BOT_CONVERSATION,
			"enabled": 0,
			"installed_by": (activity.get("from") or {}).get("name"),
			**values,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _unique_name(base: str) -> str:
	base = base[:120]
	name, i = base, 2
	while frappe.db.exists("Teams Destination", name):
		name, i = f"{base} {i}", i + 1
	return name


# ---------------------------------------------------------------- replies


def send_help_reply(service_url: str, conversation_id: str, activity_id: str | None = None):
	from notification_engine.teams.cards.builder import get_site_url

	text = _("I send ERP notifications from {0}. Open it here: {1}").format(
		auth.get_bot_settings().name, get_site_url()
	)
	activity = {"type": "message", "text": text}
	if activity_id:
		connector.reply_to_activity(service_url, conversation_id, activity_id, activity)
	else:
		connector.send_activity(service_url, conversation_id, activity)
