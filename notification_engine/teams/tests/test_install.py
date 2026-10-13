import frappe
from frappe.tests.utils import FrappeTestCase

from notification_engine.engine.events import OWN_DOCTYPES

TEAMS_DOCTYPES = (
	"Teams Settings",
	"Teams Destination",
	"Teams Rule Field",
	"Teams Rule Destination",
	"Teams Rule Button",
	"Teams Message Log",
	"Teams Digest Buffer",
	"Teams User Map",
)
ADMIN_ROLES = {"System Manager", "Teams Admin"}


class TestInstall(FrappeTestCase):
	def test_role_exists(self):
		self.assertTrue(frappe.db.exists("Role", "Teams Admin"))

	def test_doctypes_exist(self):
		for dt in TEAMS_DOCTYPES:
			self.assertTrue(frappe.db.exists("DocType", dt), dt)
			self.assertEqual(frappe.db.get_value("DocType", dt, "module"), "Teams", dt)
		for dt in ("Notification Rule", "Notification Engine Log"):
			self.assertEqual(frappe.db.get_value("DocType", dt, "module"), "Notification Engine", dt)
		# Teams rules are Notification Rules now.
		for dt in ("Teams Notification Rule", "Teams Rule Recipient"):
			self.assertFalse(frappe.db.exists("DocType", dt), dt)

	def test_teams_section_on_notification_rule(self):
		meta = frappe.get_meta("Notification Rule")
		for fieldname, options in (
			("teams_destinations", "Teams Rule Destination"),
			("teams_fields", "Teams Rule Field"),
			("teams_buttons", "Teams Rule Button"),
			("teams_personal_destination", "Teams Destination"),
		):
			self.assertEqual(meta.get_field(fieldname).options, options, fieldname)
		self.assertTrue(meta.get_field("send_teams"))

	def test_config_doctypes_restricted(self):
		for dt in ("Teams Destination", "Teams Message Log", "Teams Settings"):
			roles = {p.role for p in frappe.get_meta(dt).permissions}
			self.assertEqual(roles, ADMIN_ROLES, dt)
		roles = {p.role for p in frappe.get_meta("Notification Rule").permissions}
		self.assertIn("System Manager", roles)
		self.assertLessEqual(roles, ADMIN_ROLES)

	def test_webhook_url_is_password(self):
		self.assertEqual(frappe.get_meta("Teams Destination").get_field("webhook_url").fieldtype, "Password")

	def test_doc_event_hooks_wired(self):
		hooks = frappe.get_doc_hooks().get("*", {})
		for event, handler in (
			("after_insert", "on_after_insert"),
			("on_update", "on_update"),
			("on_submit", "on_submit"),
			("on_cancel", "on_cancel"),
			("on_trash", "on_trash"),
			("on_update_after_submit", "on_update"),
		):
			self.assertIn(f"notification_engine.engine.events.{handler}", hooks.get(event, []), event)

	def test_own_doctypes_never_trigger_rules(self):
		for dt in TEAMS_DOCTYPES:
			self.assertIn(dt, OWN_DOCTYPES)

	def test_logs_do_not_block_deleting_documents(self):
		ignored = frappe.get_hooks("ignore_links_on_delete")
		for dt in ("Teams Message Log", "Teams Digest Buffer", "Notification Engine Log"):
			self.assertIn(dt, ignored)

	def test_message_log_indexes(self):
		indexes = frappe.db.sql("show index from `tabTeams Message Log`", as_dict=True)
		cols = {(i.Key_name, i.Column_name) for i in indexes}
		self.assertTrue(any(c == "status" for _k, c in cols))
		self.assertTrue(any(k == "dedupe_key" for k, _c in cols))
