import frappe

from notification_engine.teams.tests.utils import TeamsTestCase, make_destination, make_rule


class TestRuleValidation(TeamsTestCase):
	def setUp(self):
		super().setUp()
		make_destination()

	def assertInvalid(self, **kwargs):
		self.assertRaises(frappe.ValidationError, make_rule, **kwargs)

	def test_valid_rule(self):
		rule = make_rule(
			event="Value Change",
			value_changed="status",
			condition='doc.status == "Closed"',
			fields=[{"fieldname": "priority"}, {"fieldname": "owner"}],
			body_template="{{ doc.description }}",
		)
		self.assertTrue(rule.name)

	def test_bad_condition(self):
		self.assertInvalid(condition="doc.status ==")

	def test_unknown_field(self):
		self.assertInvalid(fields=[{"fieldname": "no_such_field"}])

	def test_duplicate_field(self):
		self.assertInvalid(fields=[{"fieldname": "priority"}, {"fieldname": "priority"}])

	def test_password_field_blocked(self):
		self.assertInvalid(document_type="Email Account", fields=[{"fieldname": "password"}])

	def test_value_change_needs_field(self):
		self.assertInvalid(event="Value Change", value_changed="nope")

	def test_date_rule_needs_date_field(self):
		self.assertInvalid(event="Days Before", date_field="priority", days=1)
		self.assertTrue(make_rule(event="Days After", date_field="creation", days=1).name)

	def test_submit_needs_submittable(self):
		self.assertInvalid(event="Submit")
		self.assertInvalid(event="Cancel")

	def test_recipient_source_fields(self):
		self.assertInvalid(recipient_source="Role \u2192 Expand To Users")
		self.assertInvalid(recipient_source="Role \u2192 Expand To Users", role="No Such Role")
		self.assertInvalid(recipient_source="Document Field (User)")
		self.assertInvalid(recipient_source="Document Field (User)", document_field="nope")
		self.assertTrue(make_rule(recipient_source="Document Field (User)", document_field="owner").name)

	def test_message_needed_for_user_channels(self):
		# send_email / send_sms are left alone here: their logs commit.
		self.assertInvalid(send_system_notification=1, message="")

	def test_needs_target(self):
		self.assertInvalid(destinations=())

	def test_personal_webhook_not_a_destination(self):
		make_destination("Personal", destination_type="Webhook (Personal via Flow bot)")
		self.assertInvalid(destinations=("Personal",))

	def test_own_and_child_doctypes_blocked(self):
		self.assertInvalid(document_type="Teams Message Log")
		self.assertInvalid(document_type="Has Role")

	def test_personal_destination_must_be_personal(self):
		self.assertInvalid(personal_webhook="Test Chat")

	def test_bad_templates(self):
		self.assertInvalid(title_template="{{ doc.name ")
		self.assertInvalid(card_template="{ not json {{ doc.name }}")
		self.assertInvalid(card_template='{"type": "Other"}')


class TestDestinationValidation(TeamsTestCase):
	def test_https_required(self):
		self.assertRaises(frappe.ValidationError, make_destination, url="http://example.com/hook")

	def test_url_required_when_enabled(self):
		self.assertRaises(frappe.ValidationError, make_destination, url="")
		self.assertTrue(make_destination(enabled=0, url="").name)

	def test_url_stored_encrypted(self):
		from frappe.utils.password import get_decrypted_password

		dest = make_destination(url="https://example.invalid/hook?sig=abc")
		self.assertNotIn("sig=abc", frappe.db.get_value("Teams Destination", dest.name, "webhook_url") or "")
		self.assertEqual(
			get_decrypted_password("Teams Destination", dest.name, "webhook_url"),
			"https://example.invalid/hook?sig=abc",
		)
