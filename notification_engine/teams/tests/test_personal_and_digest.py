import json
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from notification_engine.engine.resolver import resolve_recipients
from notification_engine.teams import api
from notification_engine.teams.delivery.digest import MAX_ITEMS, flush, period_key
from notification_engine.teams.rules import get_recipients
from notification_engine.teams.tests.utils import TeamsTestCase, make_destination, make_rule, make_todo, make_user

PERSONAL = "Personal Hook"
PERSONAL_TYPE = "Webhook (Personal via Flow bot)"
ROLE_SOURCE = "Role \u2192 Expand To Users"
# Notification Engine only notifies System Users; a user with no desk role is a Website User.
DESK_ROLE = ("Teams Admin",)


def payload(log_name):
	return json.loads(frappe.db.get_value("Teams Message Log", log_name, "payload"))


def users(*names):
	return [{"user": name, "is_enabled": 1} for name in names]


class TestRecipients(TeamsTestCase):
	"""Recipients are resolved by Notification Engine; the Teams channel turns users into addresses."""

	def setUp(self):
		super().setUp()
		make_destination()
		make_destination(PERSONAL, destination_type=PERSONAL_TYPE)
		self.alice = make_user("tn-alice@example.com", roles=DESK_ROLE).name
		self.bob = make_user("tn-bob@example.com", roles=DESK_ROLE).name
		self.off = make_user("tn-off@example.com", roles=DESK_ROLE, enabled=0).name

	def resolve(self, doc, **rule_values):
		rule = make_rule(personal_webhook=PERSONAL, **rule_values)
		return [(r.user, r.email) for r in get_recipients(rule, doc, resolve_recipients(rule, doc))]

	def test_specific_users_and_dedupe(self):
		todo = make_todo()
		self.assertEqual(
			self.resolve(todo, recipients=users(self.alice, self.alice, self.bob)),
			[(self.alice, self.alice), (self.bob, self.bob)],
		)

	def test_disabled_recipient_row_skipped(self):
		todo = make_todo()
		rows = [{"user": self.alice, "is_enabled": 0}, {"user": self.bob, "is_enabled": 1}]
		self.assertEqual(self.resolve(todo, recipients=rows), [(self.bob, self.bob)])

	def test_owner(self):
		todo = make_todo()
		todo.owner = self.alice
		self.assertEqual(
			self.resolve(todo, recipient_source="Document Field (User)", document_field="owner"),
			[(self.alice, self.alice)],
		)

	def test_role_skips_disabled_users(self):
		todo = make_todo()
		rule = make_rule(name="Role Rule", personal_webhook=PERSONAL, recipient_source=ROLE_SOURCE, role="Teams Admin")
		rule.sync_from_role()
		synced = [r.user for r in rule.recipients]
		self.assertIn(self.alice, synced)
		self.assertIn(self.bob, synced)
		self.assertNotIn(self.off, synced)

		frappe.db.set_value("User", self.bob, "enabled", 0)  # left the company after the sync
		resolved = [r.user for r in get_recipients(rule, todo, resolve_recipients(rule, todo))]
		self.assertIn(self.alice, resolved)
		self.assertNotIn(self.bob, resolved)

	def test_document_field_user(self):
		todo = make_todo(allocated_to=self.bob)
		self.assertEqual(
			self.resolve(todo, recipient_source="Document Field (User)", document_field="allocated_to"),
			[(self.bob, self.bob)],
		)

	def test_assigned_to(self):
		todo = make_todo()
		todo._assign = json.dumps([self.alice, self.off])
		self.assertEqual(self.resolve(todo, recipient_source="Assigned To"), [(self.alice, self.alice)])

	def test_user_opt_out(self):
		todo = make_todo()
		rule = make_rule(personal_webhook=PERSONAL, recipients=users(self.alice, self.bob))
		frappe.get_doc(
			{"doctype": "Notification User Preference", "notification_rule": rule.name, "user": self.bob, "is_enabled": 0}
		).insert(ignore_permissions=True)
		self.assertEqual(resolve_recipients(rule, todo), [self.alice])


class TestPersonalMessages(TeamsTestCase):
	def setUp(self):
		super().setUp()
		make_destination()
		make_destination(PERSONAL, destination_type=PERSONAL_TYPE)
		self.alice = make_user("tn-alice@example.com", roles=DESK_ROLE).name

	def test_rule_sends_personal_message_with_recipient(self):
		make_rule(
			event="New",
			destinations=(),
			recipients=users(self.alice),
			personal_webhook=PERSONAL,
		)
		todo = make_todo()
		logs = frappe.get_all(
			"Teams Message Log",
			filters={"reference_name": todo.name},
			fields=["name", "destination", "recipient_user", "recipient_email"],
		)
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].destination, PERSONAL)
		self.assertEqual(logs[0].recipient_user, self.alice)
		self.assertEqual(payload(logs[0].name)["recipient"], self.alice)

	def test_group_and_personal_together(self):
		make_rule(
			event="New",
			recipients=users(self.alice, "Administrator"),
			personal_webhook=PERSONAL,
		)
		todo = make_todo()
		destinations = sorted(
			frappe.get_all("Teams Message Log", filters={"reference_name": todo.name}, pluck="destination")
		)
		# Group chat + Alice + Administrator.
		self.assertEqual(destinations, [PERSONAL, PERSONAL, "Test Chat"])

	def test_test_send_goes_only_to_current_user(self):
		make_rule(
			event="New",
			destinations=(),
			recipients=users(self.alice),
			personal_webhook=PERSONAL,
		)
		todo = make_todo()
		result = api.send_test_for_rule("Test ToDo Rule", todo.name)
		self.assertNotEqual(frappe.session.user, self.alice)
		self.assertEqual(len(result["logs"]), 1)
		self.assertEqual(
			frappe.db.get_value("Teams Message Log", result["logs"][0], "recipient_user"), frappe.session.user
		)

	def test_validation(self):
		rows = users(self.alice)
		# Personal Destination must be a personal destination.
		self.assertRaises(frappe.ValidationError, make_rule, recipients=rows, personal_webhook="Test Chat")
		self.assertRaises(
			frappe.ValidationError,
			make_rule,
			recipient_source=ROLE_SOURCE,
			role="No Such Role",
			personal_webhook=PERSONAL,
		)
		self.assertRaises(
			frappe.ValidationError,
			make_rule,
			recipient_source="Document Field (User)",
			document_field="nope",
			personal_webhook=PERSONAL,
		)

	def test_no_recipients_no_personal_message(self):
		make_rule(event="New", destinations=(), personal_webhook=PERSONAL)
		todo = make_todo()
		self.assertEqual(frappe.get_all("Teams Message Log", filters={"reference_name": todo.name}), [])


class TestDigest(TeamsTestCase):
	def setUp(self):
		super().setUp()
		make_destination()
		make_destination(PERSONAL, destination_type=PERSONAL_TYPE)

	def logs(self):
		return frappe.get_all("Teams Message Log", fields=["name", "event", "destination", "recipient_email"])

	def test_hourly_digest_buffers_then_sends_one_card(self):
		make_rule(event="Save", digest="Hourly")
		todos = [make_todo(description=f"item {i}") for i in range(3)]
		todos[0].description = "item 0 changed"
		todos[0].save()  # the same document stays one line

		self.assertEqual(self.logs(), [])
		self.assertEqual(frappe.db.count("Teams Digest Buffer"), 3)

		flush("Hourly")  # current period: nothing to send yet
		self.assertEqual(self.logs(), [])

		flush("Hourly", now=now_datetime() + timedelta(hours=1))
		logs = self.logs()
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].event, "Digest")
		self.assertEqual(frappe.db.count("Teams Digest Buffer"), 0)

		body = payload(logs[0].name)["attachments"][0]["content"]["body"]
		self.assertIn("3 update(s)", body[0]["text"])
		self.assertEqual(len(body), 4)
		self.assertTrue(all(b["text"].startswith("• [ToDo ") for b in body[1:]))
		self.assertIn("/app/todo/", body[1]["text"])

		flush("Hourly", now=now_datetime() + timedelta(hours=2))
		self.assertEqual(len(self.logs()), 1)

	def test_daily_digest_caps_items(self):
		make_rule(event="New", digest="Daily")
		for i in range(MAX_ITEMS + 5):
			make_todo(description=f"bulk {i}")
		flush("Daily", now=now_datetime() + timedelta(days=1))
		logs = self.logs()
		self.assertEqual(len(logs), 1)
		body = payload(logs[0].name)["attachments"][0]["content"]["body"]
		self.assertEqual(body[-1]["text"], "and 5 more")
		self.assertEqual(len(body), 1 + MAX_ITEMS + 1)

	def test_personal_digest_per_recipient(self):
		alice = make_user("tn-alice@example.com", roles=DESK_ROLE).name
		make_rule(
			event="New",
			digest="Hourly",
			destinations=(),
			recipients=users(alice, "Administrator"),
			personal_webhook=PERSONAL,
		)
		make_todo()
		make_todo()
		flush("Hourly", now=now_datetime() + timedelta(hours=1))
		logs = self.logs()
		self.assertEqual(sorted(l.recipient_email for l in logs), sorted([alice, frappe.db.get_value("User", "Administrator", "email")]))
		for log in logs:
			self.assertEqual(payload(log.name)["recipient"], log.recipient_email)

	def test_period_key(self):
		at = now_datetime().replace(hour=14, minute=5)
		self.assertTrue(period_key("Hourly", at).endswith(" 14"))
		self.assertEqual(period_key("Daily", at), f"Daily:{at:%Y-%m-%d}")
