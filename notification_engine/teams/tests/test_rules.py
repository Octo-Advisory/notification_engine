"""Rule matching, suppression and the Teams channel, through Notification Engine's doc_events."""

import time
from unittest.mock import patch

import frappe

from notification_engine.engine import events
from notification_engine.teams.rules import process_rule
from notification_engine.teams.tests.utils import TeamsTestCase, make_destination, make_rule, make_todo


def logs_for(docname, **filters):
	return frappe.get_all(
		"Teams Message Log", filters={"reference_name": docname, **filters}, fields=["name", "event", "rule"]
	)


class TestEventMatching(TeamsTestCase):
	def test_method_to_event_map(self):
		self.assertEqual(
			events.EVENT_MAP,
			{
				"after_insert": "After Insert",
				"on_update": "On Update",
				"on_submit": "On Submit",
				"on_cancel": "On Cancel",
				"on_trash": "On Trash",
			},
		)
		hooks = frappe.get_doc_hooks().get("*", {})
		for method, handler in (
			("after_insert", "on_after_insert"),
			("on_update", "on_update"),
			("on_submit", "on_submit"),
			("on_cancel", "on_cancel"),
			("on_trash", "on_trash"),
			# Changes to a submitted document run "On Update" rules.
			("on_update_after_submit", "on_update"),
		):
			self.assertIn(f"notification_engine.engine.events.{handler}", hooks.get(method, []), method)


class TestRuleEngine(TeamsTestCase):
	def setUp(self):
		super().setUp()
		make_destination()

	def test_new_event_queues_message(self):
		rule = make_rule(event="New")
		self.assertFalse(rule.recipients, "a rule posting only to Teams chats needs no recipients")
		todo = make_todo()
		logs = logs_for(todo.name)
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].event, "After Insert")
		self.assertEqual(logs[0].rule, rule.name)
		self.assertEqual(self.scheduled_logs(), [logs[0].name])

	def test_engine_log_row(self):
		rule = make_rule(event="New")
		todo = make_todo()
		log = logs_for(todo.name)[0]
		rows = frappe.get_all(
			"Notification Engine Log",
			filters={"reference_name": todo.name},
			fields=["notification_rule", "channel", "status", "recipient_address", "teams_message_log", "subject"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(
			(rows[0].notification_rule, rows[0].channel, rows[0].status, rows[0].recipient_address),
			(rule.name, "Teams", "Queued", "Test Chat"),
		)
		self.assertEqual(rows[0].teams_message_log, log.name)
		self.assertEqual(rows[0].subject, f"ToDo {todo.name}")

	def test_save_event(self):
		make_rule(event="Save")
		todo = make_todo()  # insert also runs on_update
		todo.description = "changed"
		todo.save()
		self.assertEqual(len(logs_for(todo.name)), 2)

	def test_delete_event(self):
		make_rule(event="Delete")
		todo = make_todo()
		self.assertEqual(len(logs_for(todo.name)), 0)
		todo.delete()
		self.assertEqual(len(logs_for(todo.name, event="On Trash")), 1)

	def test_value_change(self):
		make_rule(event="Value Change", value_changed="status")
		todo = make_todo(status="Open")
		self.assertEqual(len(logs_for(todo.name)), 0, "new documents do not count as a change")

		todo.description = "no status change"
		todo.save()
		self.assertEqual(len(logs_for(todo.name)), 0)

		todo.status = "Closed"
		todo.save()
		logs = logs_for(todo.name)
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].event, "Value Change")

	def test_condition(self):
		make_rule(event="New", condition='doc.priority == "High"')
		low = make_todo(priority="Low")
		high = make_todo(priority="High")
		self.assertEqual(len(logs_for(low.name)), 0)
		self.assertEqual(len(logs_for(high.name)), 1)

	def test_condition_error_logs_and_skips(self):
		make_rule(event="New", condition="doc.no_such_field.upper() == 'X'")
		with patch("frappe.log_error") as log_error:
			todo = make_todo()
		self.assertEqual(len(logs_for(todo.name)), 0)
		log_error.assert_called_once()
		self.assertIn("condition failed", log_error.call_args.kwargs["title"])

	def test_disabled_settings(self):
		make_rule(event="New")
		frappe.db.set_single_value("Teams Settings", "enabled", 0)
		events.clear_rule_cache()
		todo = make_todo()
		self.assertEqual(len(logs_for(todo.name)), 0)

	def test_disabled_rule(self):
		make_rule(event="New", enabled=0)
		todo = make_todo()
		self.assertEqual(len(logs_for(todo.name)), 0)

	def test_teams_not_ticked(self):
		make_rule(event="New", send_teams=0)
		todo = make_todo()
		self.assertEqual(len(logs_for(todo.name)), 0)

	def test_import_suppression(self):
		make_rule(event="New")
		frappe.flags.in_import = True
		todo = make_todo()
		self.assertEqual(len(logs_for(todo.name)), 0)

		make_rule(name="Import Rule", event="New", send_during_import=1)
		todo2 = make_todo()
		self.assertEqual([l.rule for l in logs_for(todo2.name)], ["Import Rule"])

	def test_other_bulk_operations_suppressed(self):
		make_rule(event="New")
		for flag in ("in_patch", "in_install", "in_migrate"):
			with patch.dict(frappe.local.flags, {flag: True}):
				self.assertTrue(events.in_bulk_operation(), flag)
				todo = make_todo()
			self.assertEqual(len(logs_for(todo.name)), 0, flag)
		self.assertFalse(events.in_bulk_operation())

	def test_dedupe(self):
		rule = make_rule(event="New")
		todo = make_todo()
		self.assertEqual(len(logs_for(todo.name)), 1)
		# Same rule, document version, event and destination: nothing new is queued.
		self.assertEqual(process_rule(rule, todo, []), [])
		self.assertEqual(len(logs_for(todo.name)), 1)

	def test_cooldown(self):
		make_rule(event="Save", cooldown_minutes=10)
		todo = make_todo()
		todo.description = "again"
		todo.save()
		self.assertEqual(len(logs_for(todo.name)), 1)

	def test_multiple_destinations(self):
		make_destination("Second Chat")
		make_rule(event="New", destinations=("Test Chat", "Second Chat"))
		todo = make_todo()
		self.assertEqual(len(logs_for(todo.name)), 2)

	def test_rule_cache_refreshes_on_rule_change(self):
		rule = make_rule(event="New")
		self.assertEqual(events.get_rule_index()["ToDo"]["After Insert"], [rule.name])
		rule.is_enabled = 0
		rule.save()
		self.assertNotIn("ToDo", events.get_rule_index())

	def test_no_rules_is_cheap(self):
		todo = make_todo()
		events.clear_rule_cache()
		events.get_rule_index()  # warm Redis
		local_key = frappe.cache.make_key(events.RULE_CACHE_KEY)
		runs = 200
		worst = 0.0
		start = time.perf_counter()
		for _ in range(runs):
			# Simulate a new request: per-request cache is empty, Redis is warm.
			frappe.local.cache.pop(local_key, None)
			t = time.perf_counter()
			events.on_update(todo)
			worst = max(worst, time.perf_counter() - t)
		avg_ms = (time.perf_counter() - start) / runs * 1000
		self.assertLess(avg_ms, 1, f"average {avg_ms:.3f} ms")
		self.assertLess(worst * 1000, 5, f"worst {worst * 1000:.3f} ms")


class TestDateRules(TeamsTestCase):
	def setUp(self):
		super().setUp()
		make_destination()

	def test_days_before(self):
		from frappe.utils import add_days, nowdate

		make_rule(event="Days Before", date_field="date", days=3)
		due = make_todo(date=add_days(nowdate(), 3))
		other = make_todo(date=add_days(nowdate(), 2))
		events.run_scheduled_checks()
		self.assertEqual(len(logs_for(due.name)), 1)
		self.assertEqual(len(logs_for(other.name)), 0)
		events.run_scheduled_checks()  # second run the same day is deduplicated
		self.assertEqual(len(logs_for(due.name)), 1)

	def test_days_after(self):
		from frappe.utils import add_days, nowdate

		make_rule(event="Days After", date_field="date", days=1)
		overdue = make_todo(date=add_days(nowdate(), -1))
		events.run_scheduled_checks()
		self.assertEqual(len(logs_for(overdue.name)), 1)
