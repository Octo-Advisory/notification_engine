"""Minimal Bot Connector REST client (no SDK)."""

from dataclasses import dataclass
from urllib.parse import quote

import requests

from notification_engine.teams.bot import auth

TIMEOUT_SECONDS = 10
MAX_ERROR_CHARS = 1000


@dataclass
class ConnectorResponse:
	ok: bool
	status: int | None
	data: dict
	error: str | None = None
	retry_after: float | None = None
	auth_error: bool = False  # credentials problem: retrying will not help


def _url(service_url: str, path: str) -> str:
	return service_url.rstrip("/") + path


def _request(method: str, url: str, body: dict | None = None) -> ConnectorResponse:
	"""Send an authenticated request; refresh the token once on 401."""
	for attempt in range(2):
		try:
			token = auth.get_access_token(force_refresh=attempt > 0)
		except auth.BotAuthError as e:
			return ConnectorResponse(ok=False, status=None, data={}, error=str(e), auth_error=True)
		try:
			response = requests.request(
				method,
				url,
				json=body,
				headers={"Authorization": f"Bearer {token}"},
				timeout=TIMEOUT_SECONDS,
			)
		except requests.Timeout:
			return ConnectorResponse(ok=False, status=None, data={}, error="Timed out after 10 seconds.")
		except requests.RequestException as e:
			return ConnectorResponse(ok=False, status=None, data={}, error=f"{type(e).__name__}")

		if response.status_code == 401 and attempt == 0:
			auth.clear_access_token()
			continue
		break

	try:
		data = response.json() if response.content else {}
	except ValueError:
		data = {}
	if 200 <= response.status_code < 300:
		return ConnectorResponse(ok=True, status=response.status_code, data=data)

	from notification_engine.teams.delivery.webhook import parse_retry_after

	error = data.get("error", {}) if isinstance(data, dict) else {}
	message = error.get("message") or error.get("code") or (response.text or "")
	return ConnectorResponse(
		ok=False,
		status=response.status_code,
		data=data if isinstance(data, dict) else {},
		error=f"HTTP {response.status_code}: {message}"[:MAX_ERROR_CHARS],
		retry_after=parse_retry_after(response.headers.get("Retry-After")),
	)


def send_activity(service_url: str, conversation_id: str, activity: dict) -> ConnectorResponse:
	return _request("POST", _url(service_url, f"/v3/conversations/{quote(conversation_id, safe='')}/activities"), activity)


def reply_to_activity(service_url: str, conversation_id: str, activity_id: str, activity: dict) -> ConnectorResponse:
	path = f"/v3/conversations/{quote(conversation_id, safe='')}/activities/{quote(activity_id, safe='')}"
	return _request("POST", _url(service_url, path), activity)


def update_activity(service_url: str, conversation_id: str, activity_id: str, activity: dict) -> ConnectorResponse:
	path = f"/v3/conversations/{quote(conversation_id, safe='')}/activities/{quote(activity_id, safe='')}"
	return _request("PUT", _url(service_url, path), activity)


def create_personal_conversation(service_url: str, app_id: str, tenant_id: str, member_id: str) -> ConnectorResponse:
	"""Start (or get) the 1:1 chat between the bot and a user who has the app installed."""
	body = {
		"bot": {"id": f"28:{app_id}"},
		"members": [{"id": member_id}],
		"channelData": {"tenant": {"id": tenant_id}},
	}
	return _request("POST", _url(service_url, "/v3/conversations"), body)


def get_member(service_url: str, conversation_id: str, member_id: str) -> ConnectorResponse:
	path = f"/v3/conversations/{quote(conversation_id, safe='')}/members/{quote(member_id, safe='')}"
	return _request("GET", _url(service_url, path))
