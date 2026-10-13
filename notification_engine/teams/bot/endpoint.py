"""Messaging endpoint for the Azure Bot: POST /api/method/notification_engine.teams.bot.endpoint.receive

The old Teams Notify path (/api/method/teams_notify.bot.endpoint.receive) is routed here too.
Authentication happens earlier, in notification_engine.teams.bot.auth.auth_hook (Frappe auth_hooks).
"""

import json

import frappe
from werkzeug.wrappers import Response

from notification_engine.teams.bot import auth


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive():
	settings = auth.get_bot_settings()
	if not settings.enabled:
		return Response(status=403)
	if not getattr(frappe.local, "teams_bot_claims", None):
		return Response(status=401)

	try:
		activity = json.loads(frappe.request.get_data() or b"{}")
	except ValueError:
		return Response(status=400)

	tenant = ((activity.get("channelData") or {}).get("tenant") or {}).get("id") or (
		activity.get("conversation") or {}
	).get("tenantId")
	if tenant != settings.tenant_id:
		# Not our organisation: acknowledge and ignore.
		return Response(status=200)

	# Frappe commits POST requests when they end; on failure undo only this activity's writes.
	frappe.db.savepoint("teams_bot_activity")
	try:
		result = handle(activity)
	except Exception:
		frappe.db.rollback(save_point="teams_bot_activity")
		frappe.log_error(title=f"Teams Notify: bot activity {activity.get('type')} failed")
		if activity.get("type") == "invoke":
			return _json(
				{
					"statusCode": 500,
					"type": "application/vnd.microsoft.error",
					"value": {"code": "InternalError", "message": "Something went wrong in ERP."},
				}
			)
		return Response(status=200)

	return _json(result) if result is not None else Response(status=200)


def handle(activity: dict) -> dict | None:
	"""Run the handler as the bot's service user."""
	from notification_engine.teams.bot.handlers import dispatch

	return dispatch(activity)


def _json(body: dict) -> Response:
	return Response(json.dumps(body), status=200, content_type="application/json")
