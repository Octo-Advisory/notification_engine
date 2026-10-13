"""Sender interface. Add a new delivery method by implementing Sender and registering it in SENDERS."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class OutboundMessage:
	log_name: str
	destination: Any  # Teams Destination document
	payload: dict
	recipient_email: str | None = None
	recipient_user: str | None = None
	conversation_id: str | None = None  # bot: the chat a card was posted in (for updates)
	service_url: str | None = None


@dataclass
class SendResult:
	ok: bool
	http_status: int | None = None
	retry_after: float | None = None
	activity_id: str | None = None
	conversation_id: str | None = None
	error: str | None = None
	retryable: bool = False
	extra: dict = field(default_factory=dict)


class Sender(Protocol):
	def send(self, message: OutboundMessage) -> SendResult: ...

	def update(self, message: OutboundMessage, activity_id: str) -> SendResult: ...


def get_sender(destination) -> Sender:
	from notification_engine.teams.delivery.bot import BotSender
	from notification_engine.teams.delivery.webhook import WebhookSender

	senders = {
		"Webhook": WebhookSender,
		"Webhook (Personal via Flow bot)": WebhookSender,
		"Bot Conversation": BotSender,
		"Bot (Personal Chat)": BotSender,
	}
	sender_cls = senders.get(destination.destination_type)
	if not sender_cls:
		raise NotImplementedError(f"No sender for destination type {destination.destination_type!r}")
	return sender_cls()
