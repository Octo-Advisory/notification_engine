"""Power Automate / Teams Workflows webhook sender."""

import re

import requests

from notification_engine.teams.delivery.base import OutboundMessage, SendResult

TIMEOUT_SECONDS = 10
MAX_ERROR_CHARS = 1000
# Workflow URLs carry their credential in the query string (sig=...). Never let them reach logs.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class WebhookSender:
	def send(self, message: OutboundMessage) -> SendResult:
		url = message.destination.get_password("webhook_url", raise_exception=False)
		if not url:
			return SendResult(ok=False, error="Webhook URL is not set on this destination.")

		try:
			response = requests.post(url, json=message.payload, timeout=TIMEOUT_SECONDS)
		except requests.Timeout:
			return SendResult(ok=False, retryable=True, error="Timed out after 10 seconds.")
		except requests.RequestException as e:
			return SendResult(ok=False, retryable=True, error=f"{type(e).__name__}: {redact(str(e))}")

		status = response.status_code
		if 200 <= status < 300:
			return SendResult(ok=True, http_status=status)

		return SendResult(
			ok=False,
			http_status=status,
			retryable=status == 429 or status >= 500,
			retry_after=parse_retry_after(response.headers.get("Retry-After")),
			error=f"HTTP {status}: {redact(response.text or '')}"[:MAX_ERROR_CHARS],
		)

	def update(self, message: OutboundMessage, activity_id: str) -> SendResult:
		return SendResult(ok=False, error="Webhook destinations cannot update a posted card.")


def redact(text: str) -> str:
	return _URL_RE.sub("<url>", text or "")


def parse_retry_after(value: str | None) -> float | None:
	"""Retry-After in seconds. HTTP-date values are not used by Workflows; ignore them."""
	if not value:
		return None
	try:
		return max(0.0, float(value))
	except ValueError:
		return None
