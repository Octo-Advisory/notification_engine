"""Data for the Teams Notify dashboard (/teams-notify): delivery stats and setup checks."""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, getdate, now_datetime, nowdate

from notification_engine.teams.api import ADMIN_ROLES

CHART_DAYS = 14
RECENT_FAILURES = 8
SECRET_WARN_DAYS = 30
WEBHOOK_TYPES = ("Webhook", "Webhook (Personal via Flow bot)")
BOT_TYPES = ("Bot Conversation", "Bot (Personal Chat)")
# Notification Rules that send to Teams.
TEAMS_RULES = {"send_teams": 1}


@frappe.whitelist()
def get_overview() -> dict:
	frappe.only_for(ADMIN_ROLES)
	return {
		"kpis": _kpis(),
		"daily": _daily_counts(),
		"destinations": _destination_health(),
		"failures": frappe.get_all(
			"Teams Message Log",
			filters={"status": "Failed"},
			fields=["name", "title", "destination", "rule", "http_status", "error", "modified"],
			order_by="modified desc",
			limit=RECENT_FAILURES,
		),
		"setup": _setup_checks(),
	}


@frappe.whitelist()
def get_setup_status() -> dict:
	frappe.only_for(ADMIN_ROLES)
	return _setup_checks()


def _kpis() -> dict:
	today = nowdate()
	week_start = add_days(today, -6)

	def count(status, since):
		return frappe.db.count("Teams Message Log", {"status": status, "creation": (">=", since)})

	sent_week, failed_week = count("Sent", week_start), count("Failed", week_start)
	finished = sent_week + failed_week
	return {
		"sent_today": count("Sent", today),
		"failed_today": count("Failed", today),
		"waiting": frappe.db.count("Teams Message Log", {"status": ("in", ("Queued", "Throttled"))}),
		"success_rate_7d": round(100 * sent_week / finished, 1) if finished else None,
		"active_rules": frappe.db.count("Notification Rule", TEAMS_RULES | {"is_enabled": 1}),
		"total_rules": frappe.db.count("Notification Rule", TEAMS_RULES),
		"active_destinations": frappe.db.count("Teams Destination", {"enabled": 1}),
		"failing_destinations": frappe.db.count(
			"Teams Destination", {"enabled": 1, "consecutive_failures": (">", 0)}
		),
	}


def _daily_counts() -> list[dict]:
	start = add_days(nowdate(), -(CHART_DAYS - 1))
	log = frappe.qb.DocType("Teams Message Log")
	day = frappe.query_builder.functions.Date(log.creation)
	rows = (
		frappe.qb.from_(log)
		.select(day.as_("day"), log.status, frappe.query_builder.functions.Count("*").as_("n"))
		.where(log.creation >= start)
		.groupby(day, log.status)
		.run(as_dict=True)
	)
	by_day = {}
	for r in rows:
		by_day.setdefault(str(r.day), {})[r.status] = r.n
	out = []
	for i in range(CHART_DAYS):
		d = str(getdate(add_days(start, i)))
		counts = by_day.get(d, {})
		out.append(
			{
				"date": d,
				"sent": counts.get("Sent", 0),
				"failed": counts.get("Failed", 0),
				"other": sum(v for k, v in counts.items() if k not in ("Sent", "Failed")),
			}
		)
	return out


def _destination_health() -> list[dict]:
	return frappe.get_all(
		"Teams Destination",
		fields=[
			"name",
			"destination_type",
			"enabled",
			"conversation_name",
			"last_success",
			"last_error_at",
			"last_error",
			"consecutive_failures",
		],
		order_by="enabled desc, consecutive_failures desc, name asc",
	)


def _setup_checks() -> dict:
	"""Each check is {ok, detail}. `ok` is None when the check does not apply (e.g. bot not used)."""
	from frappe.utils.scheduler import is_scheduler_disabled

	from notification_engine.teams.bot.auth import ENDPOINT_PATH, get_bot_settings, get_client_secret
	from notification_engine.teams.cards.builder import get_site_url
	from notification_engine.teams.delivery.queue import get_queue_name

	settings = frappe.get_cached_doc("Teams Settings")
	bot = get_bot_settings()
	site_url = (settings.site_url or get_site_url()).rstrip("/")
	queue = get_queue_name()
	checks = {}

	checks["scheduler"] = _check(
		not is_scheduler_disabled(verbose=False),
		_("Scheduler is enabled.") if not is_scheduler_disabled(verbose=False)
		else _("Scheduler is disabled. Run: bench --site {0} enable-scheduler").format(frappe.local.site),
	)

	workers = _workers_for(queue)
	checks["workers"] = _check(
		workers > 0,
		_("{0} worker(s) listen on the '{1}' queue.").format(workers, queue)
		if workers
		else _("No worker is listening on the '{0}' queue. Start the bench (bench start) or supervisor.").format(
			queue
		),
	)

	checks["enabled"] = _check(
		settings.enabled,
		_("Teams Notify is enabled.") if settings.enabled else _("Tick Enabled in Teams Settings."),
	)

	webhooks = frappe.db.count("Teams Destination", {"destination_type": ("in", WEBHOOK_TYPES), "enabled": 1})
	bot_convs = frappe.db.count("Teams Destination", {"destination_type": ("in", BOT_TYPES), "enabled": 1})
	checks["destination"] = _check(
		webhooks + bot_convs > 0,
		_("{0} webhook and {1} bot destination(s) enabled.").format(webhooks, bot_convs)
		if webhooks + bot_convs
		else _("Create a Teams Destination (webhook) or add the bot to a chat."),
	)

	delivered = frappe.db.get_value("Teams Destination", {"last_success": ("is", "set")}, "max(last_success)")
	checks["delivered"] = _check(
		bool(delivered),
		_("Last delivery {0}.").format(frappe.utils.pretty_date(delivered))
		if delivered
		else _("No message delivered yet. Send a test message."),
	)

	rules = frappe.db.count("Notification Rule", TEAMS_RULES | {"is_enabled": 1})
	checks["rule"] = _check(
		rules > 0,
		_("{0} rule(s) enabled.").format(rules) if rules else _("Create and enable a Notification Rule."),
	)

	# Bot checks apply only once the admin starts configuring the bot.
	bot_started = bool(bot.enabled or bot.app_id or bot.tenant_id)
	has_secret = bool(bot_started and get_client_secret())
	checks["bot_credentials"] = _check(
		bool(bot.app_id and bot.tenant_id and has_secret) if bot_started else None,
		_("App ID, Tenant ID and client secret are saved.")
		if bot.app_id and bot.tenant_id and has_secret
		else _("Enter App ID, Tenant ID and client secret in Teams Settings."),
	)
	checks["bot_enabled"] = _check(
		bool(bot.enabled) if bot_started else None,
		_("Bot is enabled.") if bot.enabled else _("Tick Bot Enabled in Teams Settings."),
	)
	checks["public_https"] = _check(
		site_url.startswith("https://") if bot_started else None,
		_("Site URL is public HTTPS.")
		if site_url.startswith("https://")
		else _("Teams can only reach an https:// Site URL. Current: {0}").format(site_url),
	)

	expiry = settings.bot_secret_expiry
	days_left = date_diff(expiry, nowdate()) if expiry else None
	checks["secret_expiry"] = _check(
		(days_left is not None and days_left > SECRET_WARN_DAYS) if bot_started else None,
		_("Secret expires in {0} days.").format(days_left)
		if days_left is not None
		else _("Enter the Secret Expiry Date so admins get a reminder."),
	)

	linked = frappe.db.count("Teams User Map", {"user": ("is", "set")})
	installed = frappe.db.count("Teams User Map", {"installed": 1})
	checks["users"] = _check(
		linked > 0 if bot_started else None,
		_("{0} Teams user(s) installed the app, {1} linked to a Frappe user.").format(installed, linked),
	)

	return {
		"checks": checks,
		"site": frappe.local.site,
		"site_url": site_url,
		"messaging_endpoint": site_url + ENDPOINT_PATH,
		"queue": queue,
		"bot_name": bot.name,
		"bot_enabled": bool(bot.enabled),
		"bot_started": bot_started,
		"secret_days_left": days_left,
		"frappe_version": frappe.__version__,
		"app_version": frappe.get_attr("notification_engine.__version__"),
		"checked_at": str(now_datetime()),
	}


def _check(ok, detail: str) -> dict:
	return {"ok": None if ok is None else bool(ok), "detail": detail}


def _workers_for(queue: str) -> int:
	from frappe.utils.background_jobs import get_workers

	try:
		workers = get_workers()
	except Exception:
		return 0
	# RQ queue names are prefixed per bench, e.g. "<bench-id>:teams".
	return sum(
		1 for w in workers if any(q == queue or q.endswith(":" + queue) for q in w.queue_names())
	)
