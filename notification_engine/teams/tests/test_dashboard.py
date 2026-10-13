import frappe
from frappe.utils import add_days, now_datetime

from notification_engine.teams.dashboard import CHART_DAYS, get_overview, get_setup_status
from notification_engine.teams.tests.utils import TeamsTestCase, make_destination, make_rule, make_user


class TestDashboard(TeamsTestCase):
	def make_log(self, status, creation=None):
		log = frappe.get_doc(
			{"doctype": "Teams Message Log", "status": status, "title": f"{status} msg", "destination": "Test Chat"}
		).insert(ignore_permissions=True, ignore_links=True)
		if creation:
			frappe.db.set_value("Teams Message Log", log.name, "creation", creation, update_modified=False)
		return log.name

	def test_overview_counts(self):
		make_destination()
		make_rule()
		self.make_log("Sent")
		self.make_log("Sent")
		failed = self.make_log("Failed")
		self.make_log("Queued")
		self.make_log("Sent", creation=add_days(now_datetime(), -3))

		data = get_overview()
		self.assertEqual(data["kpis"]["sent_today"], 2)
		self.assertEqual(data["kpis"]["failed_today"], 1)
		self.assertEqual(data["kpis"]["waiting"], 1)
		self.assertEqual(data["kpis"]["success_rate_7d"], 75.0)
		self.assertEqual(data["kpis"]["active_rules"], 1)

		self.assertEqual(len(data["daily"]), CHART_DAYS)
		today = data["daily"][-1]
		self.assertEqual((today["sent"], today["failed"], today["other"]), (2, 1, 1))
		self.assertEqual(data["daily"][-4]["sent"], 1)
		self.assertIn(failed, [f.name for f in data["failures"]])
		self.assertIn("Test Chat", [d.name for d in data["destinations"]])

	def test_setup_checks(self):
		checks = get_setup_status()["checks"]
		self.assertTrue(checks["enabled"]["ok"])
		self.assertFalse(checks["rule"]["ok"])
		make_destination()
		make_rule()
		checks = get_setup_status()["checks"]
		self.assertTrue(checks["rule"]["ok"])
		self.assertTrue(checks["destination"]["ok"])
		for key in ("scheduler", "workers", "delivered", "bot_credentials", "public_https", "users"):
			self.assertIn(key, checks)

	def test_admin_only(self):
		# frappe.only_for is a no-op while frappe.flags.in_test is set.
		user = make_user("teams-dashboard-test@example.com")
		frappe.set_user(user.name)
		frappe.flags.in_test = False
		try:
			self.assertRaises(frappe.PermissionError, get_overview)
			self.assertRaises(frappe.PermissionError, get_setup_status)
		finally:
			frappe.flags.in_test = True
			frappe.set_user("Administrator")
