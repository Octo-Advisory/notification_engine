# Copyright (c) 2026, Octo Advisory and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

WEBHOOK_TYPES = ("Webhook", "Webhook (Personal via Flow bot)")


class TeamsDestination(Document):
	def validate(self):
		if self.destination_type in WEBHOOK_TYPES:
			self.validate_webhook_url()
		elif self.destination_type == "Bot Conversation" and self.enabled and not self.conversation_id:
			frappe.throw(_("Bot conversations are created automatically when the bot is added to a chat or channel."))
		elif self.destination_type == "Bot (Personal Chat)":
			other = frappe.db.get_value(
				"Teams Destination", {"destination_type": self.destination_type, "name": ("!=", self.name)}
			)
			if other:
				frappe.throw(_("There is already a Bot (Personal Chat) destination: {0}").format(other))
		if (self.rate_per_second or 0) < 0 or (self.burst or 0) < 0:
			frappe.throw(_("Rate and Burst cannot be negative."))

	def validate_webhook_url(self):
		url = self.webhook_url
		# Password fields hold asterisks after the first save; only check a newly typed value.
		if url and set(url) != {"*"}:
			url = url.strip()
			if not url.startswith("https://"):
				frappe.throw(_("Webhook URL must start with https://"))
			self.webhook_url = url
		elif not url and self.enabled:
			frappe.throw(_("Webhook URL is required for an enabled webhook destination."))
