# Copyright (c) 2026, Octo Advisory and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
PERSONAL_BOT_DESTINATION = "Teams Bot (Personal)"


class TeamsSettings(Document):
	def validate(self):
		if self.site_url:
			self.site_url = self.site_url.strip().rstrip("/")
			if not self.site_url.startswith(("http://", "https://")):
				frappe.throw(_("Site URL must start with http:// or https://"))
		if (self.default_rate_per_second or 0) <= 0:
			frappe.throw(_("Default Rate per Second must be greater than 0."))
		if (self.default_burst or 0) < 1:
			frappe.throw(_("Default Burst must be at least 1."))
		for field in ("max_retries", "log_retention_days", "failure_alert_threshold"):
			if (self.get(field) or 0) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(self.meta.get_label(field))))
		self.validate_bot()

	def validate_bot(self):
		from notification_engine.teams.bot.auth import ENDPOINT_PATH
		from notification_engine.teams.cards.builder import get_site_url

		self.messaging_endpoint = (self.site_url or get_site_url()).rstrip("/") + ENDPOINT_PATH
		for field in ("bot_app_id", "bot_tenant_id"):
			value = (self.get(field) or "").strip()
			self.set(field, value)
			if value and not GUID_RE.match(value):
				frappe.throw(_("{0} must be a GUID like 3f7a9c21-0000-0000-0000-000000000000.").format(_(self.meta.get_label(field))))
		if self.bot_service_url and not self.bot_service_url.startswith("https://"):
			frappe.throw(_("Fallback Service URL must start with https://"))

	def on_update(self):
		from notification_engine.teams.bot.auth import _token_key

		# Password changes cannot be detected reliably (the field holds asterisks); always drop the token.
		frappe.cache.delete_value(_token_key(self.bot_app_id or ""))
		if self.bot_enabled:
			ensure_personal_bot_destination()


def ensure_personal_bot_destination():
	if frappe.db.exists("Teams Destination", {"destination_type": "Bot (Personal Chat)"}):
		return
	frappe.get_doc(
		{
			"doctype": "Teams Destination",
			"destination_name": PERSONAL_BOT_DESTINATION,
			"destination_type": "Bot (Personal Chat)",
			"enabled": 1,
		}
	).insert(ignore_permissions=True)
