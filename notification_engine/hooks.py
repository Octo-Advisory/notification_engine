from . import __version__ as app_version

app_name = "notification_engine"
app_title = "Notification Engine"
app_publisher = "Your Company"
app_description = "Generic, user-level notification engine for Frappe / ERPNext"
app_email = "dev@example.com"
app_license = "MIT"
required_apps = ["frappe"]

# Teams desk helpers (shared by the Teams forms)
app_include_js = "/assets/notification_engine/js/teams.js"

# Teams dashboard (frontend/), built to public/frontend and served at /teams-notify
website_route_rules = [{"from_route": "/teams-notify/<path:app_path>", "to_route": "teams-notify"}]

# -----------------------------------------------------------------------
# Install / migrate
# -----------------------------------------------------------------------
before_install = "notification_engine.teams.install.check_legacy_app_removed"
after_install = "notification_engine.teams.install.setup"
before_migrate = "notification_engine.teams.install.check_legacy_app_removed"

# -----------------------------------------------------------------------
# Teams bot
# -----------------------------------------------------------------------
# Authenticates Bot Connector requests to the bot endpoint (JWT, not a Frappe user).
auth_hooks = ["notification_engine.teams.bot.auth.auth_hook"]
# Azure Bots registered with the former Teams Notify app post to its endpoint; keep it working.
override_whitelisted_methods = {
	"teams_notify.bot.endpoint.receive": "notification_engine.teams.bot.endpoint.receive",
}

# Delivery logs keep a Dynamic Link to the source document; never block deleting that document.
ignore_links_on_delete = ["Teams Message Log", "Teams Digest Buffer", "Notification Engine Log"]

# -----------------------------------------------------------------------
# Document events
#
# We hook into every doctype ("*") rather than a fixed list, because the
# whole point of this engine is that any process (workflow, custom app,
# core doctype) can register a Notification Rule against it without a
# code change here.
# -----------------------------------------------------------------------
doc_events = {
	"*": {
		"after_insert": "notification_engine.engine.events.on_after_insert",
		"on_update": "notification_engine.engine.events.on_update",
		"on_submit": "notification_engine.engine.events.on_submit",
		"on_cancel": "notification_engine.engine.events.on_cancel",
		"on_trash": "notification_engine.engine.events.on_trash",
		"on_update_after_submit": "notification_engine.engine.events.on_update",
		# Workflow transitions call doc.save() under the hood (already
		# covered by on_update above), but Frappe also separately runs
		# "on_workflow_action" via doc.run_method() right after a workflow
		# button is pressed. This MUST live inside doc_events - a top-level
		# `on_workflow_action = "..."` hooks.py attribute is not a
		# recognized Frappe hook name and is silently never called.
		"on_workflow_action": "notification_engine.engine.events.on_workflow_action",
	}
}

# -----------------------------------------------------------------------
# Scheduler - for "Days Before" / "Days After" style rules (e.g. contract
# expiring in 3 days, invoice overdue by 2 days, etc.)
# -----------------------------------------------------------------------
scheduler_events = {
	# Teams: sends messages whose rate-limit wait or retry backoff is over; recovers lost jobs.
	"cron": {"* * * * *": ["notification_engine.teams.delivery.queue.process_due"]},
	"hourly": ["notification_engine.teams.delivery.digest.flush_hourly"],
	"daily": [
		"notification_engine.engine.events.run_scheduled_checks",
		"notification_engine.teams.delivery.digest.flush_daily",
		"notification_engine.teams.tasks.purge_old_logs",
		"notification_engine.teams.tasks.warn_secret_expiry",
	],
}

# -----------------------------------------------------------------------
# Fixtures - ship a couple of safe defaults with the app (none required,
# left empty intentionally; add exported Notification Rule fixtures here
# once you've built your first rules and want to version-control them).
# -----------------------------------------------------------------------
fixtures = [{"dt": "Role", "filters": [["name", "=", "Teams Admin"]]}]

# -----------------------------------------------------------------------
# Permission restrictions - users may only see/edit their own opt-out
# preference rows, not everyone else's.
# -----------------------------------------------------------------------
permission_query_conditions = {
	"Notification User Preference": "notification_engine.notification_engine.doctype.notification_user_preference.notification_user_preference.get_permission_query_conditions",
}

has_permission = {
	"Notification User Preference": "notification_engine.notification_engine.doctype.notification_user_preference.notification_user_preference.has_permission",
}
