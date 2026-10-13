# Copyright (c) 2026, Your Company and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from notification_engine.engine import events
from notification_engine.engine.resolver import users_with_designation

TEST_USER = "ne-test-user@example.com"
CHANNEL_HOOK = "notification_engine.notification_engine.doctype.notification_rule.test_notification_rule.CHANNEL"

# Stand-in for another app's channel, registered through the notification_engine_channels hook.
CHANNEL = MagicMock()


class TestNotificationRule(FrappeTestCase):
	def setUp(self):
		for dt in ("Notification Rule", "Notification Rule Recipient", "Notification Engine Log"):
			frappe.db.delete(dt)
		events.clear_rule_cache()
		self.addCleanup(events.clear_rule_cache)
		CHANNEL.reset_mock()
		if not frappe.db.exists("User", TEST_USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": TEST_USER,
					"first_name": "NE Test",
					"send_welcome_email": 0,
					"roles": [{"role": "System Manager"}],
				}
			)
			user.flags.no_welcome_mail = True
			user.insert(ignore_permissions=True)

		real_get_hooks = frappe.get_hooks

		def get_hooks(hook=None, *args, **kwargs):
			if hook == "notification_engine_channels":
				return [CHANNEL_HOOK]
			return real_get_hooks(hook, *args, **kwargs)

		patcher = patch("notification_engine.engine.dispatcher.frappe.get_hooks", side_effect=get_hooks)
		patcher.start()
		self.addCleanup(patcher.stop)
		# setUp deletes rows inside the test transaction; a commit would make that permanent.
		commit_guard = patch.object(frappe.db, "commit", side_effect=AssertionError("commit() called during a test"))
		commit_guard.start()
		self.addCleanup(commit_guard.stop)

	def make_rule(self, **kwargs):
		values = {
			"doctype": "Notification Rule",
			"title": "NE Test",
			"is_enabled": 1,
			"reference_doctype": "ToDo",
			"event": "After Insert",
			"recipient_source": "Specific Users",
			"recipients": [{"user": TEST_USER, "is_enabled": 1}],
			# on by default; its log helper commits, which would leak test rows to the site
			"send_system_notification": 0,
			"subject": "ToDo {{ doc.name }}",
			"message": "Hello",
		}
		values.update(kwargs)
		return frappe.get_doc(values).insert()

	def test_external_channel_gets_resolved_users_and_rendered_content(self):
		self.make_rule()
		todo = frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert()

		CHANNEL.assert_called_once()
		rule, doc, users, subject, message = CHANNEL.call_args.args
		self.assertEqual(doc.name, todo.name)
		self.assertEqual(users, [TEST_USER])
		self.assertEqual(subject, f"ToDo {todo.name}")
		self.assertEqual(message, "Hello")

	def test_failing_external_channel_does_not_break_the_save(self):
		self.make_rule()
		CHANNEL.side_effect = Exception("channel down")
		try:
			with patch("notification_engine.engine.dispatcher.frappe.log_error") as log_error:
				frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert()
		finally:
			CHANNEL.side_effect = None
		CHANNEL.assert_called_once()
		log_error.assert_called_once()

	def test_rule_index_is_cached_and_cleared_on_change(self):
		rule = self.make_rule()
		self.assertEqual(events.get_rule_index()["ToDo"]["After Insert"], [rule.name])

		rule.is_enabled = 0
		rule.save()
		self.assertNotIn("ToDo", events.get_rule_index())

	def test_stale_cached_rule_name_is_ignored(self):
		frappe.cache.set_value(events.RULE_CACHE_KEY, {"ToDo": {"After Insert": ["No Such Rule"]}})
		frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert()
		CHANNEL.assert_not_called()

	def test_import_does_not_notify(self):
		self.make_rule()
		frappe.flags.in_import = True
		try:
			frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert()
		finally:
			frappe.flags.in_import = False
		CHANNEL.assert_not_called()

	def test_disabled_recipient_is_skipped(self):
		self.make_rule(recipients=[{"user": TEST_USER, "is_enabled": 0}])
		frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert()
		CHANNEL.assert_not_called()

	def test_failed_log_write_keeps_the_request(self):
		from notification_engine.notification_engine.doctype.notification_engine_log.notification_engine_log import (
			create_log,
		)

		todo = frappe.get_doc({"doctype": "ToDo", "description": "keep me"}).insert()
		with patch.object(frappe, "log_error") as log_error:
			create_log(notification_rule="NE Test", channel="No Such Channel", status="Success")
		log_error.assert_called_once()
		self.assertTrue(frappe.db.exists("ToDo", todo.name))

	def test_designation_source(self):
		if frappe.db.exists("DocType", "Employee"):
			self.skipTest("ERPNext is installed on this site")
		self.assertEqual(users_with_designation("Manager"), [])
		self.assertRaisesRegex(
			frappe.ValidationError,
			"ERPNext",
			self.make_rule,
			recipient_source="Designation",
			designation="Manager",
			recipients=[],
		)
