import frappe
from frappe.utils import add_days, getdate, nowdate

from notification_engine.engine.condition import evaluate_condition
from notification_engine.engine.resolver import resolve_recipients
from notification_engine.engine.dispatcher import dispatch

RULE_CACHE_KEY = "notification_engine:rule_index"

# Saving these must never trigger a rule - writing a Notification Engine Log
# row happens on every send, so this also keeps the hot path cheap.
OWN_DOCTYPES = frozenset(
	(
		"Notification Rule",
		"Notification Rule Recipient",
		"Notification Rule Cc Bcc Recipient",
		"Notification User Preference",
		"Notification Engine Settings",
		"Notification Engine Log",
	)
)

EVENT_MAP = {
	"after_insert": "After Insert",
	"on_update": "On Update",
	"on_submit": "On Submit",
	"on_cancel": "On Cancel",
	"on_trash": "On Trash",
}


def on_after_insert(doc, method=None, **kwargs):
	_process(doc, "after_insert")


def on_update(doc, method=None, **kwargs):
	_process(doc, "on_update")
	_process_value_change(doc)


def on_submit(doc, method=None, **kwargs):
	_process(doc, "on_submit")
	# A workflow transition from Draft to Submitted calls doc.submit(), NOT
	# doc.save() - confirmed from Frappe's own apply_workflow() source. That
	# means a rule watching the workflow state field via "Value Change"
	# would silently never fire on that specific transition unless we also
	# check for the value change here, not just inside on_update.
	_process_value_change(doc)


def on_cancel(doc, method=None, **kwargs):
	_process(doc, "on_cancel")
	# Same reasoning as on_submit above - a Submitted -> Cancelled workflow
	# transition calls doc.cancel(), not doc.save().
	_process_value_change(doc)


def on_trash(doc, method=None, **kwargs):
	_process(doc, "on_trash")


def on_workflow_action(doc, method=None, **kwargs):
	# NOTE: verified against Frappe's actual apply_workflow() source -
	# core Frappe does NOT call doc.run_method("on_workflow_action")
	# anywhere. This handler is wired in defensively (in case a future
	# Frappe version, or another installed app, ever calls it) but you
	# should NOT rely on the "Workflow Action" event for anything today.
	# Use "Value Change" on the workflow state field (or "On Submit" /
	# "On Cancel", both of which now also check value changes above)
	# instead - that's the mechanism that's actually verified to work.
	_process(doc, "workflow_action")
	_process_value_change(doc)


def _should_skip(doc):
	"""Own DocTypes, and bulk operations (data import, patches, install,
	migrate) where a notification per row would flood every recipient."""
	if doc.doctype in OWN_DOCTYPES:
		return True
	return bool(
		frappe.flags.in_import or frappe.flags.in_patch or frappe.flags.in_install or frappe.flags.in_migrate
	)


def _process(doc, hook_event):
	"""Fetch and run every enabled rule whose `event` maps to this hook."""
	if _should_skip(doc):
		return

	event_label = "Workflow Action" if hook_event == "workflow_action" else EVENT_MAP.get(hook_event)
	if not event_label:
		return

	rules = _get_matching_rules(doc.doctype, event_label)
	for rule in rules:
		_run_rule(rule, doc)


def _process_value_change(doc):
	"""Value Change rules need the before-save snapshot, so they're handled
	separately from the generic event dispatch above. Called from
	on_update, on_submit, AND on_cancel (a workflow transition can trigger
	any of the three depending on the docstatus change involved) - guarded
	by a flag on the doc instance so if more than one of those hooks fires
	within the same request for the same document, the check still only
	runs once and can't send a duplicate notification.
	"""
	if _should_skip(doc) or doc.flags.get("_notification_engine_value_change_done"):
		return

	rules = _get_matching_rules(doc.doctype, "Value Change")
	if not rules:
		return

	doc_before_save = doc.get_doc_before_save()
	if not doc_before_save:
		return

	doc.flags._notification_engine_value_change_done = True

	for rule in rules:
		field = rule.value_changed_field
		if not field:
			continue
		if doc_before_save.get(field) != doc.get(field):
			_run_rule(rule, doc)


def _get_matching_rules(reference_doctype, event_label):
	names = get_rule_index().get(reference_doctype, {}).get(event_label, [])
	rules = []
	for name in names:
		try:
			rules.append(frappe.get_cached_doc("Notification Rule", name))
		except frappe.DoesNotExistError:
			# cached index outlived the rule (e.g. its insert was rolled back)
			frappe.clear_last_message()
			clear_rule_cache()
	return rules


def get_rule_index():
	"""{reference_doctype: {event: [rule names]}} for enabled rules, cached in
	Redis. These hooks run on every document save on the site, so the common
	case (no rule for this DocType) must not cost a database query.
	"""
	return frappe.cache.get_value(RULE_CACHE_KEY, generator=_load_rule_index)


def clear_rule_cache(*args, **kwargs):
	frappe.cache.delete_value(RULE_CACHE_KEY)


def _load_rule_index():
	if not frappe.db.table_exists("Notification Rule"):
		return {}

	index = {}
	for row in frappe.get_all(
		"Notification Rule",
		filters={"is_enabled": 1},
		fields=["name", "reference_doctype", "event"],
		order_by="creation asc",
	):
		index.setdefault(row.reference_doctype, {}).setdefault(row.event, []).append(row.name)
	return index


def _run_rule(rule, doc):
	if not evaluate_condition(rule.condition, doc):
		return

	users = resolve_recipients(rule, doc)
	if not users:
		return

	dispatch(rule, doc, users)


def run_scheduled_checks():
	"""Runs once a day via scheduler_events. Handles 'Days Before' / 'Days
	After' rules by scanning the target doctype for documents whose date
	field lands exactly on today + offset (or - offset).
	"""
	rules = frappe.get_all(
		"Notification Rule",
		filters={"event": ["in", ["Days Before", "Days After"]], "is_enabled": 1},
		pluck="name",
	)

	for rule_name in rules:
		rule = frappe.get_doc("Notification Rule", rule_name)
		_run_scheduled_rule(rule)


def _run_scheduled_rule(rule):
	if not rule.date_field or not rule.days_offset:
		return

	target_date = (
		add_days(nowdate(), rule.days_offset)
		if rule.event == "Days Before"
		else add_days(nowdate(), -rule.days_offset)
	)

	try:
		matching_names = frappe.get_all(
			rule.reference_doctype,
			filters={rule.date_field: getdate(target_date)},
			pluck="name",
		)
	except Exception:
		frappe.log_error(
			title="Notification Engine: scheduled rule failed to query reference doctype",
			message=f"rule={rule.name} doctype={rule.reference_doctype} field={rule.date_field}",
		)
		return

	for name in matching_names:
		doc = frappe.get_doc(rule.reference_doctype, name)
		_run_rule(rule, doc)
