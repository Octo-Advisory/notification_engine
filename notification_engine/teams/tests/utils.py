from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from notification_engine.engine.events import clear_rule_cache

TEST_WEBHOOK_URL = "https://example.invalid/powerautomate/automations/direct/workflows/abc/triggers/manual/paths/invoke?api-version=1&sig=SECRET-SIG"


# Tables a test may write to. setUp deletes them inside the test transaction, which
# FrappeTestCase rolls back at the end of the class, so the site's own rows come back.
CLEAN_DOCTYPES = (
	"Notification Rule",
	"Notification Rule Recipient",
	"Notification Rule Cc Bcc Recipient",
	"Notification User Preference",
	"Notification Engine Log",
	"Teams Rule Destination",
	"Teams Rule Field",
	"Teams Rule Button",
	"Teams Message Log",
	"Teams Digest Buffer",
)


class TeamsTestCase(FrappeTestCase):
	"""Enables Teams, stubs job scheduling, and cleans Redis keys between tests."""

	def setUp(self):
		# FrappeTestCase rolls back only per class; start each test from a clean slate.
		for dt in CLEAN_DOCTYPES:
			frappe.db.delete(dt)
		frappe.db.set_single_value(
			"Teams Settings",
			{
				"enabled": 1,
				"site_url": "",
				"queue_name": "teams",
				"default_rate_per_second": 0.07,
				"default_burst": 4,
				"max_retries": 5,
				"failure_alert_threshold": 5,
				"log_retention_days": 30,
			},
		)
		clear_rule_cache()
		frappe.cache.delete_keys("teams_notify:cooldown")
		reset_rate_limits()
		patcher = patch("notification_engine.teams.delivery.queue.schedule_delivery")
		self.scheduled = patcher.start()
		self.addCleanup(patcher.stop)
		# setUp deletes rows inside the test transaction. A commit would make that permanent on the
		# dev site, so any commit during a test is a failure. Some callers swallow exceptions
		# (Notification Engine's create_log, the dispatcher), so the attempt is also recorded and
		# checked after the test.
		self.commit_calls = []

		def refuse_commit(*args, **kwargs):
			self.commit_calls.append(args)
			raise AssertionError("commit() called during a test")

		commit_guard = patch.object(frappe.db, "commit", side_effect=refuse_commit)
		commit_guard.start()
		self.addCleanup(commit_guard.stop)
		self.addCleanup(self.assert_no_commit)

	def assert_no_commit(self):
		self.assertEqual(self.commit_calls, [], "frappe.db.commit() was called during the test")

	def tearDown(self):
		frappe.flags.in_import = False
		clear_rule_cache()
		frappe.cache.delete_keys("teams_notify:cooldown")
		reset_rate_limits()

	def scheduled_logs(self) -> list[str]:
		return [c.args[0] for c in self.scheduled.call_args_list]


def reset_rate_limits():
	# Rate-limit keys are raw Redis keys (no Frappe prefix), so delete_keys() does not match them.
	for key in frappe.cache.scan_iter(f"teams_notify:rl:{frappe.local.site}:*"):
		frappe.cache.delete(key)


def make_destination(
	name="Test Chat", destination_type="Webhook", enabled=1, url=TEST_WEBHOOK_URL, rate_per_second=100, burst=100
):
	"""Test destinations default to a generous rate limit; pass rate_per_second=0 to use Teams Settings."""
	if frappe.db.exists("Teams Destination", name):
		frappe.delete_doc("Teams Destination", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Teams Destination",
			"destination_name": name,
			"destination_type": destination_type,
			"enabled": enabled,
			"webhook_url": url,
			"rate_per_second": rate_per_second,
			"burst": burst,
		}
	).insert()


def make_user(email, roles=(), enabled=1, first_name="Teams Test"):
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"enabled": enabled,
			"send_welcome_email": 0,
			"roles": [{"role": r} for r in roles],
		}
	)
	user.flags.no_welcome_mail = True
	return user.insert(ignore_permissions=True)


# Old Teams Notification Rule field -> Notification Rule field.
FIELD_MAP = {
	"rule_name": "title",
	"document_type": "reference_doctype",
	"enabled": "is_enabled",
	"value_changed": "value_changed_field",
	"days": "days_offset",
	"title_template": "teams_title",
	"title_color": "teams_title_color",
	"body_template": "teams_body",
	"fields": "teams_fields",
	"include_open_button": "teams_include_open_button",
	"card_template": "teams_card_template",
	"all_workflow_actions": "teams_all_workflow_actions",
	"buttons": "teams_buttons",
	"personal_webhook": "teams_personal_destination",
	"cooldown_minutes": "teams_cooldown_minutes",
	"digest": "teams_digest",
}
EVENT_MAP = {
	"New": "After Insert",
	"Save": "On Update",
	"Submit": "On Submit",
	"Cancel": "On Cancel",
	"Delete": "On Trash",
}


def make_rule(name="Test ToDo Rule", destinations=("Test Chat",), **kwargs):
	"""A Notification Rule that sends to Teams only.

	Accepts the old Teams Notification Rule keyword names (see FIELD_MAP / EVENT_MAP) as well as
	Notification Rule fieldnames. The rule is inserted with `name` as its name, so tests can refer
	to it (the autoname would append today's date).

	System Notification is off (its default is on): like Email and SMS, it writes its log with
	Notification Engine's create_log, which commits.
	"""
	if frappe.db.exists("Notification Rule", name):
		frappe.delete_doc("Notification Rule", name, force=True)
	values = {
		"doctype": "Notification Rule",
		"title": name,
		"reference_doctype": "ToDo",
		"event": "After Insert",
		"is_enabled": 1,
		"recipient_source": "Specific Users",
		"send_system_notification": 0,
		"send_email": 0,
		"send_sms": 0,
		"send_teams": 1,
		"subject": "ToDo {{ doc.name }}",
		"teams_title": "ToDo {{ doc.name }}",
		"teams_destinations": [{"destination": d} for d in destinations],
	}
	for key, value in kwargs.items():
		key = FIELD_MAP.get(key, key)
		if key == "event":
			value = EVENT_MAP.get(value, value)
		values[key] = value
	return frappe.get_doc(values).insert(set_name=name)


def make_todo(**kwargs):
	return frappe.get_doc({"doctype": "ToDo", "description": "Teams Notify test", **kwargs}).insert()


def mock_response(status=200, text="", headers=None):
	response = MagicMock(spec=requests.Response)
	response.status_code = status
	response.text = text
	response.headers = headers or {}
	return response


@contextmanager
def mock_post(*responses, side_effect=None):
	with patch("notification_engine.teams.delivery.webhook.requests.post") as post:
		if side_effect is not None:
			post.side_effect = side_effect
		elif len(responses) == 1:
			post.return_value = responses[0]
		else:
			post.side_effect = list(responses)
		yield post
