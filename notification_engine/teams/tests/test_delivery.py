import json

import frappe
import requests

from notification_engine.teams import api
from notification_engine.teams.cards.builder import make_card, make_envelope
from notification_engine.teams.delivery.queue import deliver, enqueue_message, get_queue_name
from notification_engine.teams.delivery.webhook import parse_retry_after
from notification_engine.teams.tests.utils import (
	TEST_WEBHOOK_URL,
	TeamsTestCase,
	make_destination,
	mock_post,
	mock_response,
)


class TestWebhookDelivery(TeamsTestCase):
	def setUp(self):
		super().setUp()
		self.dest = make_destination()

	def queue(self, destination="Test Chat", **kwargs):
		return enqueue_message(destination, make_envelope(make_card("Hello")), title="Hello", **kwargs)

	def log(self, name):
		return frappe.get_doc("Teams Message Log", name)

	def test_success_200_and_202(self):
		for status in (200, 202):
			name = self.queue()
			with mock_post(mock_response(status)) as post:
				deliver(name)
			log = self.log(name)
			self.assertEqual(log.status, "Sent")
			self.assertEqual(log.http_status, status)
			self.assertEqual(log.attempts, 1)
			self.assertIsNotNone(log.sent_at)

			url = post.call_args.args[0]
			self.assertEqual(url, TEST_WEBHOOK_URL)
			self.assertEqual(post.call_args.kwargs["timeout"], 10)
			self.assertEqual(post.call_args.kwargs["json"]["attachments"][0]["content"]["body"][0]["text"], "Hello")

		self.dest.reload()
		self.assertEqual(self.dest.consecutive_failures, 0)
		self.assertIsNotNone(self.dest.last_success)

	def test_400_fails_and_counts(self):
		name = self.queue()
		with mock_post(mock_response(400, text="Bad card")):
			deliver(name)
		log = self.log(name)
		self.assertEqual(log.status, "Failed")
		self.assertEqual(log.http_status, 400)
		self.assertIn("Bad card", log.error)
		self.dest.reload()
		self.assertEqual(self.dest.consecutive_failures, 1)
		self.assertIn("HTTP 400", self.dest.last_error)


	def test_timeout_and_connection_error_hide_url(self):
		frappe.db.set_single_value("Teams Settings", "max_retries", 0)
		for exc in (requests.Timeout(), requests.ConnectionError(f"Max retries exceeded with url: {TEST_WEBHOOK_URL}")):
			name = self.queue()
			with mock_post(side_effect=exc):
				deliver(name)
			log = self.log(name)
			self.assertEqual(log.status, "Failed")
			self.assertNotIn("SECRET-SIG", log.error)
			self.assertNotIn("example.invalid", log.error)

	def test_error_body_with_url_is_redacted(self):
		frappe.db.set_single_value("Teams Settings", "max_retries", 0)
		name = self.queue()
		with mock_post(mock_response(500, text=f"failed calling {TEST_WEBHOOK_URL}")):
			deliver(name)
		self.assertNotIn("SECRET-SIG", self.log(name).error)

	def test_disabled_destination_skipped(self):
		name = self.queue()
		self.dest.db_set("enabled", 0)
		with mock_post(mock_response(200)) as post:
			deliver(name)
		post.assert_not_called()
		self.assertEqual(self.log(name).status, "Skipped")

	def test_global_disable_skips_but_not_tests(self):
		frappe.db.set_single_value("Teams Settings", "enabled", 0)
		normal = self.queue()
		test = self.queue(is_test=True)
		with mock_post(mock_response(200)):
			deliver(normal)
			deliver(test)
		self.assertEqual(self.log(normal).status, "Skipped")
		self.assertEqual(self.log(test).status, "Sent")

	def test_already_sent_not_resent_by_worker(self):
		name = self.queue()
		with mock_post(mock_response(200)):
			deliver(name)
		with mock_post(mock_response(200)) as post:
			deliver(name)
		post.assert_not_called()

	def test_resend(self):
		name = self.queue()
		with mock_post(mock_response(400)):
			deliver(name)
		self.scheduled.reset_mock()
		self.assertEqual(api.resend(json.dumps([name])), 1)
		log = self.log(name)
		self.assertEqual(log.status, "Queued")
		self.assertEqual(log.attempts, 0)
		self.assertEqual(self.scheduled_logs(), [name])
		with mock_post(mock_response(202)):
			deliver(name)
		self.assertEqual(self.log(name).status, "Sent")

	def test_dedupe_key_unique(self):
		self.assertIsNotNone(self.queue(dedupe_key="k1"))
		self.assertIsNone(self.queue(dedupe_key="k1"))

	def test_payload_and_url_storage(self):
		name = self.queue()
		log = self.log(name)
		self.assertNotIn("SECRET-SIG", log.payload)
		self.assertEqual(json.loads(log.payload)["type"], "message")
		self.assertNotIn("SECRET-SIG", frappe.db.get_value("Teams Destination", "Test Chat", "webhook_url") or "")

	def test_queue_fallback(self):
		# No worker is configured for "teams" in common_site_config, so jobs go to default.
		if "teams" not in frappe.get_conf().get("workers", {}):
			self.assertEqual(get_queue_name(), "default")
		frappe.db.set_single_value("Teams Settings", "queue_name", "short")
		self.assertEqual(get_queue_name(), "short")

	def test_parse_retry_after(self):
		self.assertEqual(parse_retry_after("5"), 5.0)
		self.assertIsNone(parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT"))
		self.assertIsNone(parse_retry_after(None))


class TestApi(TeamsTestCase):
	def setUp(self):
		super().setUp()
		make_destination()
		make_destination("Personal", destination_type="Webhook (Personal via Flow bot)")

	def payload(self, name):
		return json.loads(frappe.db.get_value("Teams Message Log", name, "payload"))

	def test_send_to_teams_text(self):
		name = api.send_to_teams("Test Chat", text="Server is up", title="Status")
		body = self.payload(name)["attachments"][0]["content"]["body"]
		self.assertEqual([b["text"] for b in body], ["Status", "Server is up"])
		self.assertNotIn("recipient", self.payload(name))

	def test_send_to_teams_card_with_reference(self):
		card = make_card("Custom")
		name = api.send_to_teams("Test Chat", card=card, reference_doctype="User", reference_name="Administrator")
		log = frappe.get_doc("Teams Message Log", name)
		self.assertEqual(log.reference_name, "Administrator")
		self.assertEqual(self.payload(name)["attachments"][0]["content"]["body"][0]["text"], "Custom")

	def test_send_to_teams_personal(self):
		name = api.send_to_teams("Personal", text="Hi", recipient_user="Administrator")
		email = frappe.db.get_value("User", "Administrator", "email")
		self.assertEqual(self.payload(name)["recipient"], email)
		self.assertRaises(frappe.ValidationError, api.send_to_teams, "Personal", text="Hi")

	def test_send_to_teams_bad_destination(self):
		self.assertRaises(frappe.ValidationError, api.send_to_teams, "Nope", text="x")

	def test_send_test_to_destination(self):
		name = api.send_test_to_destination("Test Chat")
		log = frappe.get_doc("Teams Message Log", name)
		self.assertEqual(log.is_test, 1)
		self.assertTrue(self.payload(name)["attachments"][0]["content"]["body"][0]["text"].startswith("[TEST]"))

	def test_send_test_for_rule(self):
		from notification_engine.teams.tests.utils import make_rule, make_todo

		make_rule(event="Value Change", value_changed="status", condition='doc.status == "Closed"')
		todo = make_todo(status="Open")
		result = api.send_test_for_rule("Test ToDo Rule", todo.name)
		self.assertEqual(len(result["logs"]), 1)
		self.assertFalse(result["condition"])
		title = self.payload(result["logs"][0])["attachments"][0]["content"]["body"][0]["text"]
		self.assertEqual(title, f"[TEST] ToDo {todo.name}")
		# Test sends are never deduplicated.
		self.assertEqual(len(api.send_test_for_rule("Test ToDo Rule", todo.name)["logs"]), 1)

	def test_ui_methods_need_admin_role(self):
		# frappe.only_for is a no-op while frappe.flags.in_test is set.
		frappe.set_user("Guest")
		frappe.flags.in_test = False
		try:
			self.assertRaises(frappe.PermissionError, api.send_test_to_destination, "Test Chat")
			self.assertRaises(frappe.PermissionError, api.resend, "x")
			self.assertRaises(frappe.PermissionError, api.send_test_for_rule, "x")
		finally:
			frappe.flags.in_test = True
			frappe.set_user("Administrator")
