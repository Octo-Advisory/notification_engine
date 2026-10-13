"""Teams bot sender: group chats, channels and personal chats through the Bot Connector."""

import frappe
from frappe.utils import now_datetime

from notification_engine.teams.bot import auth, connector
from notification_engine.teams.delivery.base import OutboundMessage, SendResult

BOT_CONVERSATION = "Bot Conversation"
BOT_PERSONAL = "Bot (Personal Chat)"
RETRYABLE = {408, 412, 429, 500, 502, 503, 504}
NOT_INSTALLED = "Teams app not installed for this user"


class BotSender:
	def send(self, message: OutboundMessage) -> SendResult:
		activity = to_activity(message.payload)
		if message.destination.destination_type == BOT_PERSONAL:
			return self._send_personal(message, activity)

		dest = message.destination
		if not (dest.conversation_id and dest.service_url):
			return SendResult(ok=False, error="This bot destination has no conversation. Add the bot to the chat again.")
		return _result(connector.send_activity(dest.service_url, dest.conversation_id, activity), dest.conversation_id)

	def update(self, message: OutboundMessage, activity_id: str) -> SendResult:
		conversation_id = message.conversation_id or message.destination.conversation_id
		service_url = message.service_url or message.destination.service_url or auth.get_bot_settings().service_url
		response = connector.update_activity(service_url, conversation_id, activity_id, to_activity(message.payload))
		return _result(response, conversation_id, activity_id=activity_id)

	def _send_personal(self, message: OutboundMessage, activity: dict) -> SendResult:
		user_map = find_user_map(message.recipient_user, message.recipient_email)
		if not user_map or not user_map.installed or not (user_map.teams_user_id or user_map.aad_object_id):
			who = message.recipient_user or message.recipient_email or "?"
			return SendResult(ok=False, error=f"{NOT_INSTALLED} ({who}). Install the Teams app for them, or check Teams User Map.")

		settings = auth.get_bot_settings()
		service_url = user_map.service_url or settings.service_url
		conversation_id = user_map.conversation_id
		if not conversation_id:
			created = connector.create_personal_conversation(
				service_url, settings.app_id, settings.tenant_id, user_map.teams_user_id or user_map.aad_object_id
			)
			if not created.ok:
				return _result(created, None, installed_check=user_map)
			conversation_id = created.data.get("id")
			frappe.db.set_value(
				"Teams User Map", user_map.name, {"conversation_id": conversation_id, "service_url": service_url}
			)

		response = connector.send_activity(service_url, conversation_id, activity)
		if response.status == 404:
			# The stored chat is gone; forget it so the next try creates a new one.
			frappe.db.set_value("Teams User Map", user_map.name, "conversation_id", None)
			response.retry_after = 0
			return SendResult(ok=False, http_status=404, retryable=True, error=response.error)
		return _result(response, conversation_id, installed_check=user_map)


def to_activity(payload: dict) -> dict:
	"""Logs store the webhook envelope; the bot sends the same attachments as a message activity."""
	return {"type": "message", "attachments": payload.get("attachments") or []}


def find_user_map(user: str | None, email: str | None):
	name = None
	if user:
		name = frappe.db.get_value("Teams User Map", {"user": user})
	if not name and email:
		name = frappe.db.get_value("Teams User Map", {"teams_email": email})
	return frappe.get_doc("Teams User Map", name) if name else None


def _result(response, conversation_id, activity_id=None, installed_check=None) -> SendResult:
	if response.ok:
		return SendResult(
			ok=True,
			http_status=response.status,
			activity_id=response.data.get("id") or activity_id,
			conversation_id=conversation_id,
		)
	if installed_check is not None and response.status == 403:
		# Uninstalled or blocked (e.g. subCode MessageWritesBlocked): stop trying until Teams says otherwise.
		frappe.db.set_value("Teams User Map", installed_check.name, {"installed": 0, "last_seen": now_datetime()})
		return SendResult(ok=False, http_status=403, error=f"{NOT_INSTALLED} or the user blocked the bot. {response.error}")
	return SendResult(
		ok=False,
		http_status=response.status,
		retryable=not response.auth_error and (response.status is None or response.status in RETRYABLE),
		retry_after=response.retry_after,
		error=response.error,
	)
