import frappe
from frappe import _
from frappe.model.document import Document


class NotificationUserPreference(Document):
	def validate(self):
		self.validate_duplicate()

	def validate_duplicate(self):
		existing = frappe.db.exists(
			"Notification User Preference",
			{
				"user": self.user,
				"notification_rule": self.notification_rule,
				"name": ["!=", self.name],
			},
		)
		if existing:
			frappe.throw(
				_("A preference for user {0} and rule {1} already exists").format(
					self.user, self.notification_rule
				)
			)


def get_permission_query_conditions(user):
	"""Non-admins may only see/edit their own preference rows."""
	if not user:
		user = frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return ""
	return f"(`tabNotification User Preference`.user = {frappe.db.escape(user)})"


def has_permission(doc, ptype=None, user=None):
	if not user:
		user = frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return True
	return doc.user == user
