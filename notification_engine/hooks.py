from . import __version__ as app_version

app_name = "notification_engine"
app_title = "Notification Engine"
app_publisher = "Your Company"
app_description = "Generic, user-level notification engine for Frappe / ERPNext"
app_email = "dev@example.com"
app_license = "MIT"

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
	"daily": [
		"notification_engine.engine.events.run_scheduled_checks",
	]
}

# -----------------------------------------------------------------------
# Fixtures - ship a couple of safe defaults with the app (none required,
# left empty intentionally; add exported Notification Rule fixtures here
# once you've built your first rules and want to version-control them).
# -----------------------------------------------------------------------
fixtures = []

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
